"""Descarga el modelo GGUF usado por analitica/analysis.py (narrativa de reportes). Se corre una
sola vez por entorno — el .gguf pesa un par de GB y no se versiona en git (ver .gitignore:
`.models/`).

Uso:
    python manage.py download_llm_model
    python manage.py download_llm_model --repo Qwen/Qwen2.5-1.5B-Instruct-GGUF --file qwen2.5-1.5b-instruct-q4_k_m.gguf
"""
from django.core.management.base import BaseCommand

from analitica.analysis import DEFAULT_MODEL_FILE, DEFAULT_MODEL_REPO, MODELS_DIR


class Command(BaseCommand):
    help = 'Descarga el modelo GGUF para la narrativa de reportes de analitica.'

    def add_arguments(self, parser):
        parser.add_argument('--repo', default=DEFAULT_MODEL_REPO,
                             help=f'Repositorio de Hugging Face (default: {DEFAULT_MODEL_REPO}).')
        parser.add_argument('--file', default=DEFAULT_MODEL_FILE,
                             help=f'Nombre del archivo .gguf dentro del repo (default: {DEFAULT_MODEL_FILE}).')

    def handle(self, *args, **options):
        from huggingface_hub import hf_hub_download

        repo, filename = options['repo'], options['file']
        self.stdout.write(f'Descargando {filename} desde {repo} a {MODELS_DIR} ...')
        MODELS_DIR.mkdir(parents=True, exist_ok=True)
        path = hf_hub_download(repo_id=repo, filename=filename, local_dir=str(MODELS_DIR))
        self.stdout.write(self.style.SUCCESS(f'Listo: {path}'))
        self.stdout.write(
            'Si usaste --repo/--file distintos al default, exporta KUNSAMU_LLM_MODEL_FILE con ese '
            'nombre de archivo (ver analitica/analysis.py) para que la app lo use.'
        )
