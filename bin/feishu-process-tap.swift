import CoreAudio
import Foundation

let aggregateName = "全局系统输出旁路（CoreAudio Global Tap）"
let aggregateUID = "com.admin.local-meeting-assistant.feishu-process-tap"
let defaultBundleID = "com.electron.lark"

func fail(_ message: String, _ code: Int32 = 1) -> Never {
    fputs("process tap: \(message)\n", stderr)
    exit(code)
}

func pidArguments() -> [pid_t] {
    var pids: [pid_t] = []
    var index = 1
    while index < CommandLine.arguments.count {
        if CommandLine.arguments[index] == "--pid", index + 1 < CommandLine.arguments.count,
           let pid = Int32(CommandLine.arguments[index + 1]), pid > 0 {
            pids.append(pid_t(pid))
            index += 2
        } else {
            index += 1
        }
    }
    return Array(Set(pids)).sorted()
}

func bundleArgument() -> String? {
    guard let index = CommandLine.arguments.firstIndex(of: "--bundle-id"), index + 1 < CommandLine.arguments.count else {
        return nil
    }
    return CommandLine.arguments[index + 1]
}

func isGlobalArgument() -> Bool {
    CommandLine.arguments.contains("--global")
}

@available(macOS 15.0, *)
func run() throws {
    let system = AudioHardwareSystem.shared
    if CommandLine.arguments.contains("--cleanup") {
        if let existing = try? system.device(forUID: aggregateUID) {
            _ = AudioHardwareDestroyAggregateDevice(existing.id)
            usleep(250_000)
        }
        for tap in (try? system.taps) ?? [] {
            try? system.destroyProcessTap(tap)
        }
        FileHandle.standardOutput.write(Data("CLEANED\n".utf8))
        return
    }
    let pids = pidArguments()
    let bundleID = bundleArgument()
    let global = isGlobalArgument()
    guard global || !pids.isEmpty || bundleID != nil else { fail("missing --pid, --bundle-id, or --global") }
    let processes = try pids.compactMap { try system.process(for: $0) }
    if !global && bundleID == nil && processes.isEmpty { fail("no CoreAudio process found for pids \(pids)") }

    let description: CATapDescription
    let mode: String
    let outputRoute: String
    if global {
        description = CATapDescription(monoGlobalTapButExcludeProcesses: [])
        description.isMono = true
        description.isMixdown = true
        mode = "global-mix"
        outputRoute = "all-process-output"
    } else if !processes.isEmpty {
        // Bundle matching is useful for discovery, but explicit CoreAudio
        // processes are the reliable capture route for Electron's Iron audio
        // service. The Python supervisor refreshes these PIDs after restarts.
        description = CATapDescription(monoMixdownOfProcesses: processes.map(\.id))
        mode = "processes"
        outputRoute = ""
    } else if let bundleID {
        description = CATapDescription()
        description.bundleIDs = [bundleID]
        description.isProcessRestoreEnabled = true
        description.isMono = true
        description.isMixdown = true
        mode = "bundle"
        outputRoute = ""
    } else {
        fail("no CoreAudio process found for pids \(pids)")
    }
    description.name = aggregateName
    description.isPrivate = false
    description.muteBehavior = .unmuted

    if let existing = try? system.device(forUID: aggregateUID) {
        _ = AudioHardwareDestroyAggregateDevice(existing.id)
        usleep(250_000)
    }
    guard let tap = try system.makeProcessTap(description: description) else {
        fail("AudioHardwareSystem.makeProcessTap returned nil")
    }

    let aggregateDescription: [String: Any] = [
        "name": aggregateName,
        "uid": aggregateUID,
        "taps": [["uid": try tap.uid, "drift": true]],
        "private": 0,
        "stacked": 0,
        "tapautostart": 1,
    ]
    guard let aggregate = try system.makeAggregateDevice(description: aggregateDescription) else {
        try? system.destroyProcessTap(tap)
        fail("AudioHardwareSystem.makeAggregateDevice returned nil")
    }

    let readyBundle = bundleID ?? ""
    let ready = "READY name=\(aggregateName) uid=\(try aggregate.uid) tap=\(try tap.uid) mode=\(mode) output=\(outputRoute) bundle=\(readyBundle) pids=\(pids)\n"
    FileHandle.standardOutput.write(ready.data(using: .utf8)!)
    let cleanup = {
        try? system.destroyAggregateDevice(aggregate)
        try? system.destroyProcessTap(tap)
        exit(0)
    }
    let signalSources = [SIGINT, SIGTERM].map { signalNumber -> DispatchSourceSignal in
        signal(signalNumber, SIG_IGN)
        let source = DispatchSource.makeSignalSource(signal: signalNumber, queue: .main)
        source.setEventHandler(handler: cleanup)
        source.resume()
        return source
    }
    withExtendedLifetime(signalSources) {
        dispatchMain()
    }
}

if #available(macOS 15.0, *) {
    do { try run() }
    catch { fail(String(describing: error)) }
} else {
    fail("macOS 15 or newer is required", 2)
}
