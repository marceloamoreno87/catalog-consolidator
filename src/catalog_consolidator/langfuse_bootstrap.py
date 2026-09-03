"""Cria uma versão local inicial do prompt no Langfuse."""

from dotenv import load_dotenv

from .langfuse import LangfuseCatalogObserver, LangfuseSettings


def main() -> int:
    load_dotenv(".env")
    settings = LangfuseSettings.from_environment()
    if settings is None:
        raise SystemExit("Defina LANGFUSE_PUBLIC_KEY e LANGFUSE_SECRET_KEY antes de inicializar o prompt.")
    LangfuseCatalogObserver(settings).bootstrap_prompt()
    print(f"Prompt criado: {settings.prompt_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
