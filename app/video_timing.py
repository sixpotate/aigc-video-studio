"""Frame-aligned speech timing and short, readable subtitle phrases."""
import math
import re


def plan_timing(durations, target_seconds, fps=25):
    if len(durations) != 4 or any(not math.isfinite(d) or d <= 0 for d in durations):
        raise ValueError('四段配音必须完整且有效。')
    frames = round(target_seconds * fps)
    speech_budget = frames / fps - .32 * len(durations)
    tempo = max(1.0, sum(durations) / speech_budget)
    if tempo > 1.35:
        raise ValueError('台词超出所选时长，压缩会导致语速过快。请减少台词，或选择30秒后重新生成分镜。')
    ideal = [(d / tempo + .32) * fps for d in durations]
    spare = frames - sum(ideal)
    ideal = [f + spare * d / sum(durations) for f, d in zip(ideal, durations)]
    counts = [math.floor(f) for f in ideal]
    for i in sorted(range(4), key=lambda i: ideal[i] - counts[i], reverse=True)[:frames-sum(counts)]:
        counts[i] += 1
    return tempo, [count / fps for count in counts]


def subtitle_phrases(text, width=14):
    parts = re.findall(r'[^，。！？；、：,.!?;:]+[，。！？；、：,.!?;:]*', text)
    return [part[i:i+width] for part in parts for i in range(0, len(part), width)] or [text]
