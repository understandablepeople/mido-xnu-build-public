"""Lossless nonzero arithmetic spans for exact diagnostic table comparison."""


def encode(words):
    spans = []
    position = 0
    while position < len(words):
        if words[position] == 0:
            position += 1
            continue
        start = position
        step = 0
        if position + 1 < len(words) and words[position + 1]:
            step = (words[position + 1] - words[position]) & 0xffffffffffffffff
        position += 1
        while position < len(words) and words[position] and words[position] == (
                words[start] + (position - start) * step) & 0xffffffffffffffff:
            position += 1
        spans.append(dict(start=start, count=position-start, value=words[start], step=step))
    return spans


def decode(spans, count):
    words = [0] * count
    previous_end = 0
    for span in spans:
        start, end = span["start"], span["start"] + span["count"]
        if span["count"] <= 0 or not previous_end <= start < end <= count:
            raise ValueError("Invalid overlapping or out-of-range reference span")
        for position in range(start, end):
            words[position] = (span["value"] + (position-start)*span["step"]) & 0xffffffffffffffff
        previous_end = end
    return words
