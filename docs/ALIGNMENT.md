# Alignment contract

1. Store original utterance start/end times and text. Each reviewed English segment retains its source segment ID.
2. Partition the complete source timeline into utterance intervals and source gaps. Nothing is removed or reordered. Small overlaps from ASR are clamped; review the source near chunk boundaries.
3. Generate coherent narration per reviewed utterance, cache by content/settings, and measure the resulting WAV. Reject empty/over-limit scripts before TTS.
4. For source interval length `S` and speech length `A`, tempo is `min(1.12, max(1, A/S))`. Final interval length is `ceil(max(S,A/tempo)*30)/30`. Speech is never cut to fit a shorter video. Pitch is preserved using `atempo`.
5. Retain all original moving frames at their original pace; append a last-frame hold to fill the final interval. When speech finishes early, retain source duration with silence rather than stretching narration unnaturally. Preserve gaps with silent audio. Normalize audio to mono 48 kHz.
6. Each final interval starts at the previous final end. The next source interval uses its original timestamp independently, so accumulated dubbing extensions do not detach subsequent source activity from its narration. Concat durations are explicitly supplied to avoid per-file AAC padding extending anchors. Every source/final anchor, tempo, hold and review flag is persisted in the database and exported as JSON.
7. Render intermediate H.264/AAC intervals to disk with 30 fps constant frame rate, source dimensions (even pixels), then concatenate into a fast-start MP4. Reject a final duration differing from planned duration by more than 250 ms. Frame quantization can extend total duration by up to one frame per interval; this is part of the mapped timeline, not hidden drift.

   A sub-frame interval uses its preceding source frame when necessary, preventing an audio-only interval at the very end of a recording. This boundary choice is accurate to one output frame.
8. Generate subtitle cues from `final_start` through `speech_end`, excluding padded silence, in chunks of up to 12 words. These are proportional cue estimates rather than ASR word alignment of generated speech. SRT uses comma milliseconds, VTT uses decimal milliseconds.
9. Generate notes from reviewed text in bounded batches with validated segment-ID citations; map their citations to the final English video timeline.

## Manual review

Flags identify holds greater than max(2 seconds, 25% of the source interval). Export requires explicit acceptance. The entire synchronized video is available as a preview first. Continuous handwriting, animated diagrams and live code execution can become awkward when held at the last frame. Revise the English segment, regenerate it, and review again. A future editor could allow manually choosing an anchor/hold frame; this version uses the last frame only.

ASR chunking uses fixed 300-second boundaries. A word at a cut can be imperfectly recognized; there is currently no overlapping-chunk reconciliation or forced alignment. Technical, mathematical and code-switch accuracy require human review. Source audio is replaced entirely, so non-speech demonstration sounds are also removed. No lip synchronization is attempted.
