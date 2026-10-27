from pathlib import Path


def test_dockerfile_copy_sources_exist_inside_compose_build_context():
    """COPY sources must resolve inside the Compose build context, not repository root."""
    context = Path(__file__).resolve().parents[1]
    dockerfile = context / "Dockerfile"
    sources = [
        line.split()[1]
        for line in dockerfile.read_text().splitlines()
        if line.strip().startswith("COPY ")
    ]
    assert sources, "Dockerfile must copy application sources"
    for source in sources:
        source_path = Path(source)
        assert not source_path.is_absolute()
        assert ".." not in source_path.parts
        assert (context / source_path).exists(), (
            f"COPY source {source!r} is outside/missing from Docker Compose build context {context}"
        )
