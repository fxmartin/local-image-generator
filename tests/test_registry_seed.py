"""The shipped registry.yaml: real Phase 0 hashes, licenses, pins, alternative sets."""

import pytest

from lig.models.registry import load_registry

# sha256/size taken from the Phase 0 downloads (docs/bench/xps13.md).
SDCPP_Q4 = {
    "qwen_image_2.1-Q4_K.gguf": (
        "29f9c83c249ff0292fb2943fceddfa2319b446601866c82a4f8be062abea72c2",
        4197494816,
    ),
    "Qwen3VL-8B-Instruct-Q4_K_M.gguf": (
        "67d1659bfe71b89d50b45a4ad1a9e5b997e5bb16ce5da66a6a6167abd569e9e2",
        5027784800,
    ),
    "qwen_image_2.1_vae_bf16.safetensors": (
        "bb21f7473051e1ac368515dd3f2e15cd44d7a11748ee8823e1ddca3e4876b7c9",
        675509688,
    ),
    "mmproj-Qwen3VL-8B-Instruct-F16.gguf": (
        "ca524100ebf825c9a870db1c580d03879e0da0ab2541697e2458e64891cf9d38",
        1159029824,
    ),
}


@pytest.fixture(scope="module")
def reg():
    return load_registry()


def test_no_placeholder_hashes_or_sizes(reg):
    for artifact in reg.artifacts:
        assert set(artifact.sha256) != {"0"}, artifact.name
        assert artifact.size_bytes > 1, artifact.name


def test_sdcpp_q4_set_matches_phase0_downloads(reg):
    resolved = {a.filename: (a.sha256, a.size_bytes) for a in reg.set_for("sdcpp", "linux")}
    assert resolved == SDCPP_Q4
    assert [a.role for a in reg.set_for("sdcpp", "linux")] == [
        "transformer",
        "text_encoder",
        "vae",
        "mmproj",
    ]


def test_vae_description_warns_2_1_only(reg):
    vae = reg.get("qwen-image-2.1-vae")
    assert "2.1" in vae.description
    assert "interchangeable" in vae.description


def test_every_artifact_has_license_and_pinned_engine(reg):
    for artifact in reg.artifacts:
        assert artifact.license, artifact.name
        assert artifact.pinned_engine, artifact.name
        assert artifact.description, artifact.name


def test_community_conversions_carry_the_qwen_research_license(reg):
    # Model cards checked 2026-09-25: none of these is Apache-2.0.
    assert reg.get("qwen-image-2.1-q4-transformer").license == "qwen-research"
    assert reg.get("qwen-image-2.1-vae").license == "qwen-research"
    assert reg.get("qwen-image-2.1-text-encoder").license == "apache-2.0"
    assert reg.get("qwen-image-2.1-mmproj").license == "apache-2.0"


def test_q8_is_an_alternative_set_not_the_default(reg):
    names = list(reg.sets)
    assert names[0] == "sdcpp-q4"
    assert "sdcpp-q8" in names
    assert [a.name for a in reg.set_for("sdcpp", "linux")][0] == "qwen-image-2.1-q4-transformer"
    q8 = [reg.get(n) for n in reg.sets["sdcpp-q8"].artifacts]
    transformer = next(a for a in q8 if a.role == "transformer")
    assert transformer.filename == "qwen_image_2.1-Q8_0.gguf"
    assert transformer.sha256 == "f8b244b00937f0e444a40dbf7866460871b89b30142594973b6012d1b471dc0a"
    assert transformer.size_bytes == 7687155744


def test_ncnn_bundle_set(reg):
    bundle = reg.set_for("ncnn", "linux")
    assert len(bundle) == 17
    assert {a.role for a in bundle} == {"bundle"}
    assert all(a.filename.startswith("qwenimage21/") for a in bundle)
    assert 31.0e9 < sum(a.size_bytes for a in bundle) < 31.4e9  # 31.19 GB per the bench doc
    assert all("20260924" in a.pinned_engine for a in bundle)
    assert all(a.license == "qwen-research" for a in bundle)
