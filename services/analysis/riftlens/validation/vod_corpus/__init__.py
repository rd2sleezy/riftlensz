"""Real-VOD corpus inventory, labelling, and H.9.1/H.10 evaluation helpers."""

from riftlens.validation.vod_corpus.kinds import MediaKind
from riftlens.validation.vod_corpus.manifest import VodCorpus, VodEntry, load_corpus
from riftlens.validation.vod_corpus.verdicts import CorpusVerdicts, compute_verdicts

__all__ = [
    "CorpusVerdicts",
    "MediaKind",
    "VodCorpus",
    "VodEntry",
    "compute_verdicts",
    "load_corpus",
]
