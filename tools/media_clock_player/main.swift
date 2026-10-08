// Media-clock player for PRISM bench trials (host only).
//
// Plays one WAV through the default output with AVAudioEngine and reports the
// audio device's own render position, so a trial can pace descriptor records
// from the actual playback clock rather than from process launch time.
// Every report line is JSON on stdout:
//   {"event":"start", ...}
//   {"event":"clock","uptime_ns":N,"render_uptime_ns":N,"render_sample":S,"latency_s":L}
//   {"event":"end", ...}
// uptime_ns is CLOCK_UPTIME_RAW (the clock Python reads with
// time.clock_gettime_ns(time.CLOCK_UPTIME_RAW)). The sample at the speaker at
// time T is render_sample + (T - render_uptime_ns)*rate/1e9 - latency_s*rate.
// latency_s is the output node's reported presentation latency, not a
// measured acoustic delay.
import AVFoundation
import Foundation

func uptimeNs() -> UInt64 { clock_gettime_nsec_np(CLOCK_UPTIME_RAW) }
var timebase = mach_timebase_info_data_t()
mach_timebase_info(&timebase)
func hostToNs(_ host: UInt64) -> UInt64 { host * UInt64(timebase.numer) / UInt64(timebase.denom) }
func emit(_ object: [String: Any]) {
  let data = try! JSONSerialization.data(withJSONObject: object, options: [.sortedKeys])
  FileHandle.standardOutput.write(data)
  FileHandle.standardOutput.write("\n".data(using: .utf8)!)
}

var args = CommandLine.arguments.dropFirst()
var path: String? = nil
var reportMs = 5.0
var inputGain = 1.0
while let a = args.popFirst() {
  switch a {
  case "--wav": path = args.popFirst()
  case "--gain": inputGain = Double(args.popFirst() ?? "invalid") ?? .nan
  case "--report-ms": reportMs = Double(args.popFirst() ?? "5") ?? 5
  default:
    FileHandle.standardError.write("usage: media_clock_player --wav FILE [--report-ms 5]\n".data(using: .utf8)!)
    exit(2)
  }
}
guard inputGain.isFinite, inputGain > 0, inputGain <= 1, reportMs.isFinite, reportMs >= 1, reportMs <= 20,
      let wav = path, let file = try? AVAudioFile(forReading: URL(fileURLWithPath: wav)) else {
  FileHandle.standardError.write("cannot open wav\n".data(using: .utf8)!)
  exit(2)
}
let engine = AVAudioEngine()
let player = AVAudioPlayerNode()
engine.attach(player)
// One frozen scalar for every source/arm, applied by the audio render graph.
player.volume = Float(inputGain)
engine.connect(player, to: engine.mainMixerNode, format: file.processingFormat)
let rate = file.processingFormat.sampleRate
let frames = file.length
player.scheduleFile(file, at: nil, completionHandler: nil)
do { try engine.start() } catch {
  FileHandle.standardError.write("engine start failed: \(error)\n".data(using: .utf8)!)
  exit(3)
}
let latency = engine.outputNode.presentationLatency
emit(["event": "start", "wav": wav, "file_rate": rate, "frames": frames,
      "input_gain": inputGain, "gain_application": "AVAudioPlayerNode.volume-fixed-render-graph-scalar",
      "output_rate": engine.outputNode.outputFormat(forBus: 0).sampleRate,
      "latency_s": latency, "uptime_ns": uptimeNs(), "clock": "CLOCK_UPTIME_RAW"])
player.play()
let endSample = Double(frames) + (latency + 0.25) * rate
var last: Double = -1
while true {
  if let nodeTime = player.lastRenderTime, nodeTime.isHostTimeValid,
     let pt = player.playerTime(forNodeTime: nodeTime), pt.isSampleTimeValid {
    let sample = Double(pt.sampleTime)
    if sample != last {
      emit(["event": "clock", "uptime_ns": uptimeNs(), "render_uptime_ns": hostToNs(nodeTime.hostTime),
            "render_sample": sample, "latency_s": latency])
      last = sample
    }
    if sample >= endSample { break }
  }
  Thread.sleep(forTimeInterval: reportMs / 1000)
}
player.stop()
engine.stop()
emit(["event": "end", "uptime_ns": uptimeNs(), "frames": frames])
