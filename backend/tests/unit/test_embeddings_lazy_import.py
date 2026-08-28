import subprocess
import sys


def test_importing_embeddings_module_does_not_load_torch_or_transformers():
    """Confirmed live: this deployment's production config
    (ENABLE_EMBEDDING=false, see render.yaml) never calls embed_text/
    embed_texts/_tokenizer/_model at all, yet every process paid torch and
    transformers' full import cost (~200-400MB of RSS) anyway, because the
    old top-level `import torch` in embeddings.py ran the moment ANYTHING
    imported that module -- including main.py itself, unconditionally, at
    process startup.

    Must run in a fresh subprocess, not in-process: other tests in this
    suite import torch for real (test_embeddings.py, test_search_api.py),
    which would make an in-process `'torch' not in sys.modules` assertion
    pass or fail based on test ORDER rather than on what embeddings.py's
    import actually does.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; import app.core.embeddings; "
            "print('torch' in sys.modules); print('transformers' in sys.modules)",
        ],
        capture_output=True,
        text=True,
        cwd=".",
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    torch_loaded, transformers_loaded = result.stdout.strip().splitlines()
    assert torch_loaded == "False", "torch was imported just by importing app.core.embeddings"
    assert transformers_loaded == "False", "transformers was imported just by importing app.core.embeddings"
