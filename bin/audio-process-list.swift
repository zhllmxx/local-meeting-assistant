import CoreAudio
import Foundation

@available(macOS 15.0, *)
func main() throws {
    let system = AudioHardwareSystem.shared
    for device in try system.devices {
        print("device id=\(device.id) uid=\(try device.uid) name=\(try device.name) type=\(type(of: device))")
    }
    for tap in try system.taps {
        print("tap id=\(tap.id) uid=\(try tap.uid)")
    }
    for process in try system.processes {
        let pid = try process.pid
        guard pid > 0 else { continue }
        let devices = (try? process.devices) ?? []
        let deviceNames = devices.compactMap { try? $0.name }.joined(separator: ",")
        let bundle = try process.bundleID ?? ""
        let output = try process.isRunningOutput
        print("pid=\(pid) bundle=\(bundle) output=\(output) devices=\(deviceNames)")
    }
}

if #available(macOS 15.0, *) {
    do { try main() }
    catch { fputs("audio process list failed: \(error)\n", stderr); exit(1) }
} else {
    fputs("macOS 15 or newer is required\n", stderr)
    exit(2)
}
