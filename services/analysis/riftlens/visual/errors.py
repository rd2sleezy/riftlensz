from __future__ import annotations


class VisualSpikeError(ValueError):
    """Base error for the V.0 visual spike. Never raised by production coaching."""


class ArtifactMissing(VisualSpikeError):
    """The R.10 media artifact path does not exist."""


class MalformedVideo(VisualSpikeError):
    """The artifact exists but cannot be decoded as a video."""


class EmptyClip(VisualSpikeError):
    """The artifact decodes but contains no usable video frames."""


class CaptureWindowError(VisualSpikeError):
    """The requested finding-window capture interval is invalid or unusable."""


class CaptureNotRequested(CaptureWindowError):
    """V.1 will not auto-capture; an explicit research capture action is required."""
