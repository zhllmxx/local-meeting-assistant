import CoreMedia
import CoreAudio
import Foundation
import ScreenCaptureKit

var retainedStream: SCStream?
var retainedOutput: AudioOutput?

final class AudioOutput: NSObject, SCStreamOutput, SCStreamDelegate {
    private let lock = NSLock()
    private var callbacks = 0
    private var formatLogged = false

    private func fail(_ message: String) -> Never {
        fputs("screen audio capture failed: \(message)\n", stderr)
        fflush(stderr)
        exit(3)
    }

    func stream(_ stream: SCStream, didStopWithError error: Error) {
        fail(String(describing: error))
    }

    func stream(_ stream: SCStream, didOutputSampleBuffer sampleBuffer: CMSampleBuffer, of outputType: SCStreamOutputType) {
        guard outputType == .audio, CMSampleBufferDataIsReady(sampleBuffer) else { return }
        guard let format = CMSampleBufferGetFormatDescription(sampleBuffer),
              let asbd = CMAudioFormatDescriptionGetStreamBasicDescription(format)?.pointee else {
            fail("missing audio format")
        }
        guard asbd.mFormatID == kAudioFormatLinearPCM,
              (asbd.mFormatFlags & kAudioFormatFlagIsFloat) != 0,
              (asbd.mFormatFlags & kAudioFormatFlagIsBigEndian) == 0,
              asbd.mBitsPerChannel == 32, asbd.mSampleRate == 48_000 else {
            fail("unsupported PCM format rate=\(asbd.mSampleRate) flags=\(asbd.mFormatFlags) bits=\(asbd.mBitsPerChannel)")
        }
        let frames = CMSampleBufferGetNumSamples(sampleBuffer)
        guard frames > 0 else { return }
        var size = 0
        CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer, bufferListSizeNeededOut: &size, bufferListOut: nil, bufferListSize: 0,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: nil)
        guard size >= MemoryLayout<AudioBufferList>.size else { fail("empty audio buffer list") }
        let storage = UnsafeMutableRawPointer.allocate(byteCount: size, alignment: MemoryLayout<AudioBufferList>.alignment)
        defer { storage.deallocate() }
        let list = storage.bindMemory(to: AudioBufferList.self, capacity: 1)
        var retainedBlock: CMBlockBuffer?
        let status = CMSampleBufferGetAudioBufferListWithRetainedBlockBuffer(
            sampleBuffer, bufferListSizeNeededOut: nil, bufferListOut: list, bufferListSize: size,
            blockBufferAllocator: nil, blockBufferMemoryAllocator: nil, flags: 0, blockBufferOut: &retainedBlock)
        guard status == noErr else { fail("audio buffer list error=\(status)") }
        // Read each buffer by frame: stereo can arrive as separate channel
        // planes or interleaved samples. Emit one Float32 per frame at 48 kHz;
        // ffmpeg performs the filtered resampling to the ASR's 16 kHz PCM.
        let buffers = UnsafeMutableAudioBufferListPointer(list)
        let channels = buffers.reduce(0) { $0 + Int($1.mNumberChannels) }
        guard channels > 0, channels == Int(asbd.mChannelsPerFrame) else { fail("invalid channel layout") }
        var mono = [Float32](repeating: 0, count: frames)
        withExtendedLifetime(retainedBlock) {
            for buffer in buffers {
                let count = Int(buffer.mNumberChannels)
                guard let data = buffer.mData,
                      Int(buffer.mDataByteSize) >= frames * count * MemoryLayout<Float32>.size else {
                    fail("truncated audio buffer")
                }
                let samples = data.assumingMemoryBound(to: Float32.self)
                for frame in 0..<frames {
                    for channel in 0..<count {
                        mono[frame] += samples[frame * count + channel] / Float32(channels)
                    }
                }
            }
        }
        let output = mono.withUnsafeBytes { Data($0) }
        lock.lock()
        if !formatLogged {
            formatLogged = true
            fputs("format rate=\(asbd.mSampleRate) channels=\(asbd.mChannelsPerFrame) flags=\(asbd.mFormatFlags) bytes=\(asbd.mBytesPerFrame)\n", stderr)
        }
        callbacks += 1
        if callbacks == 1 || callbacks % 20 == 0 {
            fputs("callbacks=\(callbacks) bytes=\(output.count)\n", stderr)
            fflush(stderr)
        }
        lock.unlock()
        FileHandle.standardOutput.write(output)
    }
}

@main
struct Main {
    static func main() async {
        do {
            let content = try await SCShareableContent.excludingDesktopWindows(false, onScreenWindowsOnly: false)
            guard let display = content.displays.first else {
                fputs("no display\n", stderr)
                exit(2)
            }
            let filter = SCContentFilter(display: display, excludingApplications: [], exceptingWindows: [])
            let config = SCStreamConfiguration()
            config.capturesAudio = true
            config.excludesCurrentProcessAudio = true
            config.sampleRate = 48_000
            config.channelCount = 2
            config.width = 2
            config.height = 2
            let output = AudioOutput()
            let stream = SCStream(filter: filter, configuration: config, delegate: output)
            try stream.addStreamOutput(output, type: .audio, sampleHandlerQueue: DispatchQueue(label: "screen-audio-capture"))
            try await stream.startCapture()
            retainedOutput = output
            retainedStream = stream
            fputs("READY display=\(display.displayID)\n", stderr)
            try await Task.sleep(nanoseconds: 86_400_000_000_000)
        } catch {
            fputs("screen audio capture failed: \(error)\n", stderr)
            exit(1)
        }
    }
}
