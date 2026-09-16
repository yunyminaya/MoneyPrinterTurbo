from __future__ import annotations

import argparse
import json
import math
import os
import re
import shutil
from typing import TYPE_CHECKING, Sequence
from uuid import UUID, uuid4

from loguru import logger

if TYPE_CHECKING:
    from app.models.schema import MaterialInfo, VideoParams


DEFAULT_VOICE_NAME = "zh-CN-XiaoxiaoNeural-Female"
_PIPELINE_STAGES = ("script", "terms", "audio", "subtitle", "materials", "video")
_CUSTOM_AUDIO_EXTENSIONS = {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg"}


class _CliHelpFormatter(
    argparse.ArgumentDefaultsHelpFormatter,
    argparse.RawDescriptionHelpFormatter,
):
    """在保留多行示例排版的同时，自动展示有意义的默认值。"""

    def _get_help_string(self, action):
        help_text = action.help or ""
        if (
            "%(default)" not in help_text
            and action.default not in (None, "", argparse.SUPPRESS)
            and action.option_strings
            and "default:" not in help_text.lower()
            and "predeterminado:" not in help_text.lower()
        ):
            help_text += " (predeterminado: %(default)s)"
        return help_text


def _positive_int(value: str) -> int:
    parsed = int(value)
    if parsed < 1:
        raise argparse.ArgumentTypeError(f"el valor debe ser >= 1, se recibió {parsed}")
    return parsed


def _paragraph_count(value: str) -> int:
    parsed = int(value)
    if parsed < 1 or parsed > 10:
        raise argparse.ArgumentTypeError(
            f"paragraph-number debe estar entre 1 y 10, se recibió {parsed}"
        )
    return parsed


def _non_negative_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0:
        raise argparse.ArgumentTypeError(f"el valor debe ser un número finito >= 0, se recibió {value!r}")
    return parsed


def _positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError(f"el valor debe ser un número finito > 0, se recibió {value!r}")
    return parsed


def _percent_position(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed < 0 or parsed > 100:
        raise argparse.ArgumentTypeError(
            f"custom-position debe ser un número finito entre 0 y 100, se recibió {value!r}"
        )
    return parsed


def _hex_color(value: str) -> str:
    if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
        raise argparse.ArgumentTypeError(
            f"el color debe usar el formato #RRGGBB, se recibió {value!r}"
        )
    return value


def _task_id(value: str) -> str:
    """CLI 自定义任务标识只接受 UUID，避免该值被解释为文件系统路径。"""
    try:
        return str(UUID(value.strip()))
    except (AttributeError, ValueError) as exc:
        raise argparse.ArgumentTypeError(
            f"task-id debe ser un UUID válido, se recibió {value!r}"
        ) from exc


_TRANSITION_MODE_VALUES = {
    "none": None,
    "shuffle": "Shuffle",
    "fade-in": "FadeIn",
    "fade-out": "FadeOut",
    "slide-in": "SlideIn",
    "slide-out": "SlideOut",
}


def _transition_mode(value: str) -> str | None:
    normalized = value.strip().lower()
    if normalized not in _TRANSITION_MODE_VALUES:
        allowed = ", ".join(_TRANSITION_MODE_VALUES)
        raise argparse.ArgumentTypeError(
            f"video-transition-mode debe ser uno de: {allowed}"
        )
    return _TRANSITION_MODE_VALUES[normalized]


def _bgm_type(value: str) -> str:
    normalized = value.strip().lower()
    if normalized == "none":
        return ""
    if normalized in {"", "random", "custom", "sonilo"}:
        return normalized
    raise argparse.ArgumentTypeError(
        "bgm-type debe ser uno de: none, random, custom, sonilo"
    )


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Genera videos de MoneyPrinterTurbo sin usar la WebUI.\n\n"
            "Los ajustes y credenciales de los proveedores se leen desde config.toml.\n"
            "La generación completa por defecto requiere un LLM configurado y una "
            "clave API de Pexels.\n"
            "La voz predeterminada de Edge TTS no requiere clave API."
        ),
        epilog="""
Ejemplos:
  Generar un video completo con la voz predeterminada de Edge TTS:
    uv run python cli.py --video-subject "Cómo la IA está cambiando la vida cotidiana"

  Generar a partir de archivos locales. Las rutas relativas usan el directorio
  de trabajo actual; también se aceptan rutas absolutas:
    uv run python cli.py --video-subject "Cómo la IA está cambiando la vida cotidiana" \\
      --video-source local --video-materials "./1.mp4,./2.mp4"

  Generar con un guion preparado y sin voz:
    uv run python cli.py --video-script "Tu guion completo" \\
      --voice-name no-voice --stop-at video

  Detenerse tras la generación del guion:
    uv run python cli.py --video-subject "Cómo la IA está cambiando la vida cotidiana" --stop-at script

Etapas del proceso:
  script     Genera o devuelve el guion.
  terms      Genera los términos de búsqueda de material; no disponible con materiales locales.
  audio      Genera TTS, audio en silencio, o usa --custom-audio-file.
  subtitle   Genera subtítulos cuando están activados.
  materials  Descarga materiales en línea o preprocesa archivos locales.
  video      Genera el video final y ejecuta la publicación cruzada configurada.
  El comando se detiene inmediatamente después de la etapa seleccionada e imprime el resultado de esa etapa.

Salida y código de estado:
  Los archivos de la tarea se escriben en storage/tasks/<task-id>/. Un comando
  exitoso imprime un objeto JSON en la salida estándar y termina con 0. Las tareas
  fallidas terminan con 1; los errores de argumentos terminan con 2. Los registros
  de ejecución se escriben en la salida de error.
""",
        formatter_class=_CliHelpFormatter,
    )

    content_group = parser.add_argument_group("guion y contenido")
    content_group.add_argument(
        "--video-subject",
        default="",
        help="tema del video; requerido a menos que se proporcione --video-script",
    )
    content_group.add_argument(
        "--video-script",
        default="",
        help="guion completo; omite la generación del guion por LLM cuando se proporciona",
    )
    content_group.add_argument(
        "--video-terms",
        default=None,
        help="términos de búsqueda de material separados por comas; se generan automáticamente si se omiten",
    )
    content_group.add_argument(
        "--video-language",
        default=None,
        help=(
            "código de idioma del guion, como zh-CN o en-US (predeterminado: detección automática)"
        ),
    )
    content_group.add_argument(
        "--paragraph-number",
        type=_paragraph_count,
        default=None,
        help="número de párrafos generados del guion, de 1 a 10 (predeterminado: 1)",
    )
    content_group.add_argument(
        "--video-script-prompt",
        default=None,
        help="requisitos adicionales para la generación del guion por LLM",
    )
    content_group.add_argument(
        "--custom-system-prompt",
        default=None,
        help="reemplaza el prompt de sistema predeterminado del LLM para la generación del guion",
    )

    material_group = parser.add_argument_group("materiales y proceso")
    material_group.add_argument(
        "--video-source",
        default="pexels",
        choices=["pexels", "pixabay", "coverr", "local"],
        help="proveedor de material de video; los proveedores en línea requieren claves API correspondientes en config.toml",
    )
    material_group.add_argument(
        "--video-materials",
        default="",
        metavar="PATH[,PATH...]",
        help=(
            "rutas de imágenes/videos locales separados por comas para --video-source local; las "
            "rutas relativas usan el directorio de trabajo actual, luego storage/local_videos como "
            "alternativa de compatibilidad; se aceptan rutas absolutas"
        ),
    )
    material_group.add_argument(
        "--stop-at",
        default="video",
        choices=_PIPELINE_STAGES,
        help="detenerse después de esta etapa del proceso; consulta el orden de etapas más abajo",
    )

    video_group = parser.add_argument_group("salida de video")
    video_group.add_argument(
        "--video-count",
        type=_positive_int,
        default=1,
        help="número de videos de salida, al menos 1",
    )
    video_group.add_argument(
        "--video-aspect",
        choices=["9:16", "16:9", "1:1"],
        default="9:16",
        help="relación de aspecto de salida: vertical, horizontal o cuadrada",
    )
    video_group.add_argument(
        "--video-concat-mode",
        choices=["random", "sequential"],
        default=None,
        help="orden de concatenación de los clips de origen (predeterminado: random)",
    )
    video_group.add_argument(
        "--video-transition-mode",
        type=_transition_mode,
        default=None,
        metavar="{none,shuffle,fade-in,fade-out,slide-in,slide-out}",
        help="transición aplicada entre clips de origen (predeterminado: none)",
    )
    video_group.add_argument(
        "--video-clip-duration",
        type=_positive_int,
        default=None,
        help=(
            "duración máxima de cada clip de origen en segundos, al menos 1 (predeterminado: 5)"
        ),
    )
    video_group.add_argument(
        "--match-materials-to-script",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "preserva el orden de las palabras clave del guion al seleccionar y concatenar "
            "materiales (predeterminado: desactivado)"
        ),
    )
    video_group.add_argument(
        "--n-threads",
        type=_positive_int,
        default=None,
        help="número de hilos de trabajo de FFmpeg, al menos 1 (predeterminado: 2)",
    )

    audio_group = parser.add_argument_group("voz y música de fondo")
    audio_group.add_argument(
        "--voice-name",
        default=DEFAULT_VOICE_NAME,
        help=(
            "identificador de voz TTS; usa 'no-voice' para salida en silencio. Los identificadores "
            "específicos de proveedor usan prefijos como gemini:, mimo:, elevenlabs: y chatterbox:"
        ),
    )
    audio_group.add_argument(
        "--voice-volume",
        type=_non_negative_float,
        default=None,
        help=(
            "multiplicador del volumen final de la voz, un número finito >= 0 (predeterminado: 1.0)"
        ),
    )
    audio_group.add_argument(
        "--voice-rate",
        type=_positive_float,
        default=None,
        help=(
            "multiplicador de la velocidad de habla, un número finito > 0 (predeterminado: 1.0)"
        ),
    )
    audio_group.add_argument(
        "--custom-audio-file",
        default=None,
        metavar="PATH",
        help=(
            "voz existente en MP3/WAV/M4A/AAC/FLAC/OGG; las rutas relativas usan el "
            "directorio de trabajo actual. Esto omite el TTS; configura "
            "subtitle_provider=whisper para transcribirla"
        ),
    )
    audio_group.add_argument(
        "--bgm-type",
        type=_bgm_type,
        default=None,
        metavar="{none,random,custom,sonilo}",
        help=(
            "modo de música de fondo; Sonilo lee su clave API desde config.toml o "
            "SONILO_API_KEY; --bgm-file implica custom si se omite "
            "(predeterminado: random)"
        ),
    )
    audio_group.add_argument(
        "--sonilo-bgm-prompt",
        default=None,
        help="prompt opcional de estilo musical para Sonilo, hasta 2000 caracteres",
    )
    audio_group.add_argument(
        "--bgm-file",
        default=None,
        metavar="PATH",
        help=(
            "archivo de audio admitido personalizado dentro de storage/bgm o resource/songs; "
            "acepta un nombre de archivo o una ruta gestionada permitida"
        ),
    )
    audio_group.add_argument(
        "--bgm-volume",
        type=_non_negative_float,
        default=None,
        help=(
            "multiplicador del volumen de la música de fondo, un número finito >= 0 (predeterminado: 0.2)"
        ),
    )

    subtitle_group = parser.add_argument_group("subtítulos")
    subtitle_group.add_argument(
        "--subtitle-enabled",
        default=True,
        action=argparse.BooleanOptionalAction,
        help=(
            "activa los subtítulos; usa --no-subtitle-enabled para desactivarlos "
            "(predeterminado: activados)"
        ),
    )
    subtitle_group.add_argument(
        "--font-name",
        default=None,
        help=(
            "nombre del archivo de fuente de subtítulos dentro de resource/fonts "
            "(predeterminado: STHeitiMedium.ttc)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-position",
        choices=["top", "center", "bottom", "custom"],
        default=None,
        help=(
            "posición vertical de los subtítulos (predeterminado: [ui].subtitle_position "
            "desde config.toml; bottom si no se configura)"
        ),
    )
    subtitle_group.add_argument(
        "--custom-position",
        type=_percent_position,
        default=None,
        help=(
            "posición personalizada como porcentaje desde arriba, 0-100; requiere "
            "--subtitle-position custom (predeterminado: [ui].custom_position desde "
            "config.toml; 70 si no se configura)"
        ),
    )
    subtitle_group.add_argument(
        "--text-fore-color",
        type=_hex_color,
        default=None,
        help=(
            "color del texto de los subtítulos en formato #RRGGBB; pon el valor entre "
            "comillas en shells que tratan # como comentario (predeterminado: #FFFFFF)"
        ),
    )
    subtitle_group.add_argument(
        "--font-size",
        type=_positive_int,
        default=None,
        help="tamaño de fuente de los subtítulos (predeterminado: 60)",
    )
    subtitle_group.add_argument(
        "--stroke-color",
        type=_hex_color,
        default=None,
        help="color del contorno de los subtítulos en formato #RRGGBB (predeterminado: #000000)",
    )
    subtitle_group.add_argument(
        "--stroke-width",
        type=_non_negative_float,
        default=None,
        help=(
            "ancho del contorno de los subtítulos, un número finito >= 0 (predeterminado: 1.5)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-background-enabled",
        default=None,
        action=argparse.BooleanOptionalAction,
        help=(
            "activa el fondo de los subtítulos; usa --no-subtitle-background-enabled para "
            "desactivarlo (predeterminado: activado)"
        ),
    )
    subtitle_group.add_argument(
        "--subtitle-background-color",
        type=_hex_color,
        default=None,
        help="color de fondo de los subtítulos en formato #RRGGBB (predeterminado: #000000)",
    )
    subtitle_group.add_argument(
        "--rounded-subtitle-background",
        default=None,
        action=argparse.BooleanOptionalAction,
        help="usa un fondo redondeado para los subtítulos (predeterminado: desactivado)",
    )

    execution_group = parser.add_argument_group("ejecución")
    execution_group.add_argument(
        "--task-id",
        type=_task_id,
        default=None,
        help="UUID personalizado usado para storage/tasks/<task-id>; se genera automáticamente si se omite",
    )
    args = parser.parse_args(argv)

    if not args.video_subject.strip() and not args.video_script.strip():
        parser.error("se requiere --video-subject o --video-script")

    if args.video_source == "local" and args.stop_at == "terms":
        parser.error(
            "--stop-at terms no tiene efecto con --video-source local "
            "(no se generan términos de búsqueda para fuentes locales)"
        )

    stage_requires_materials = args.stop_at in {"materials", "video"}
    has_video_materials = bool((args.video_materials or "").strip())
    if args.video_source == "local" and stage_requires_materials and not has_video_materials:
        parser.error(
            "se requiere --video-materials con --video-source local cuando "
            "--stop-at es materials o video"
        )
    if args.video_source != "local" and has_video_materials:
        parser.error("--video-materials solo puede usarse con --video-source local")

    if args.bgm_file:
        if args.bgm_type in (None, "custom"):
            args.bgm_type = "custom"
        else:
            parser.error("--bgm-file solo puede combinarse con --bgm-type custom")

    if args.sonilo_bgm_prompt:
        if args.bgm_type in (None, "sonilo"):
            args.bgm_type = "sonilo"
        else:
            parser.error(
                "--sonilo-bgm-prompt solo puede combinarse con --bgm-type sonilo"
            )

    if args.custom_position is not None and args.subtitle_position != "custom":
        parser.error("--custom-position requiere --subtitle-position custom")
    if args.stop_at == "subtitle" and not args.subtitle_enabled:
        parser.error("--stop-at subtitle no puede combinarse con --no-subtitle-enabled")
    if args.subtitle_background_enabled is False and (
        args.subtitle_background_color is not None
        or args.rounded_subtitle_background is True
    ):
        parser.error(
            "el color de fondo de los subtítulos o el redondeado no pueden activarse "
            "junto con --no-subtitle-background-enabled"
        )

    return args


def build_video_params(args: argparse.Namespace) -> VideoParams:
    # 参数帮助和校验不需要加载应用配置。仅在真正构建任务参数时导入模型，
    # 避免执行 ``cli.py -h`` 时产生配置初始化日志。
    from app.models.schema import MaterialInfo, VideoParams

    video_terms = args.video_terms
    if video_terms:
        video_terms = [
            term.strip() for term in re.split(r"[,，]", video_terms) if term.strip()
        ]

    video_materials = None
    materials_arg = args.video_materials or ""
    if materials_arg.strip():
        video_materials = [
            # Actual duration will be detected during video processing; use 0 as placeholder.
            MaterialInfo(provider="local", url=item.strip(), duration=0)
            for item in materials_arg.split(",")
            if item.strip()
        ]

    params_kwargs = {
        "video_subject": args.video_subject.strip(),
        "video_script": args.video_script,
        "video_terms": video_terms,
        "video_source": args.video_source,
        "video_materials": video_materials,
        "video_count": args.video_count,
        "video_aspect": args.video_aspect,
        "voice_name": args.voice_name,
        "subtitle_enabled": args.subtitle_enabled,
    }

    optional_arg_names = [
        "video_language",
        "paragraph_number",
        "video_script_prompt",
        "custom_system_prompt",
        "video_concat_mode",
        "video_transition_mode",
        "video_clip_duration",
        "match_materials_to_script",
        "n_threads",
        "voice_volume",
        "voice_rate",
        "custom_audio_file",
        "bgm_type",
        "bgm_file",
        "bgm_volume",
        "sonilo_bgm_prompt",
        "font_name",
        "subtitle_position",
        "custom_position",
        "text_fore_color",
        "font_size",
        "stroke_color",
        "stroke_width",
        "rounded_subtitle_background",
    ]
    for name in optional_arg_names:
        value = getattr(args, name)
        if value is not None:
            params_kwargs[name] = value

    if args.subtitle_background_enabled is False:
        params_kwargs["text_background_color"] = False
        params_kwargs["rounded_subtitle_background"] = False
    elif args.subtitle_background_color is not None:
        params_kwargs["text_background_color"] = args.subtitle_background_color
    elif args.subtitle_background_enabled is True:
        params_kwargs["text_background_color"] = True

    return VideoParams(**params_kwargs)


def _resolve_cli_file(
    raw_path: str,
    *,
    description: str,
    fallback_dir: str | None = None,
) -> str:
    """
    将 CLI 文件参数按当前工作目录解析为绝对路径，
    并在任务开始前确认存在。

    本地素材旧版本始终相对 ``storage/local_videos`` 解析。为兼容已有脚本，
    当前目录找不到相对路径时允许回退该目录；绝对路径始终按用户输入
    直接解析。
    """
    expanded_path = os.path.expanduser(raw_path.strip())
    if not expanded_path:
        raise ValueError(f"la ruta {description} no puede estar vacía")

    candidate = (
        expanded_path
        if os.path.isabs(expanded_path)
        else os.path.join(os.getcwd(), expanded_path)
    )
    resolved_path = os.path.realpath(candidate)
    if not os.path.isfile(resolved_path) and fallback_dir and not os.path.isabs(expanded_path):
        resolved_path = os.path.realpath(os.path.join(fallback_dir, expanded_path))

    if not os.path.isfile(resolved_path):
        raise ValueError(f"el archivo {description} no existe: {raw_path}")
    return resolved_path


def _path_is_within_directory(file_path: str, directory: str) -> bool:
    try:
        return os.path.commonpath(
            [os.path.realpath(directory), os.path.realpath(file_path)]
        ) == os.path.realpath(directory)
    except ValueError:
        # Windows 不同盘符无法计算 commonpath，此时文件显然不在目标目录内。
        return False


def _resolve_managed_resource_file(
    raw_path: str,
    *,
    resource_dir: str,
    description: str,
) -> str:
    """解析项目资源文件，并确保绝对路径仍位于对应资源目录内。"""
    from app.utils import utils

    expanded_path = os.path.expanduser(raw_path.strip())
    candidates = (
        [expanded_path]
        if os.path.isabs(expanded_path)
        else [
            os.path.join(resource_dir, expanded_path),
            os.path.join(utils.root_dir(), expanded_path),
        ]
    )
    for candidate in candidates:
        resolved_path = os.path.realpath(candidate)
        if os.path.isfile(resolved_path) and _path_is_within_directory(
            resolved_path, resource_dir
        ):
            return resolved_path
    raise ValueError(
        f"el archivo {description} debe existir dentro de {resource_dir}: {raw_path}"
    )


def prepare_cli_files(params: VideoParams, stop_at: str) -> None:
    """
    在调用 LLM/TTS 前准备 CLI 文件，避免长流程运行到后期才报告路径错误。

    服务层为了保护 API 请求，只允许读取 ``storage/local_videos`` 内的素材。
    CLI 是本地入口，接受当前目录相对路径和绝对路径。目录外素材会
    复制到受控目录，再把参数替换为服务层可安全使用的绝对路径。
    """
    from app.models import const
    from app.services import bgm as bgm_service
    from app.utils import utils

    local_material_extensions = {
        *(f".{extension}" for extension in const.FILE_TYPE_VIDEOS),
        *(f".{extension}" for extension in const.FILE_TYPE_IMAGES),
        ".avi",
        ".flv",
    }

    if params.custom_audio_file:
        params.custom_audio_file = _resolve_cli_file(
            params.custom_audio_file,
            description="audio personalizado",
        )
        audio_extension = os.path.splitext(params.custom_audio_file)[1].lower()
        if audio_extension not in _CUSTOM_AUDIO_EXTENSIONS:
            allowed = ", ".join(sorted(_CUSTOM_AUDIO_EXTENSIONS))
            raise ValueError(
                f"tipo de audio personalizado no admitido {audio_extension or '<none>'}; "
                f"extensiones permitidas: {allowed}"
            )

    if params.bgm_type == "custom":
        if not bgm_service.should_use_bgm(params.bgm_type, params.bgm_volume):
            # 0 音量时下游会统一跳过所有 BGM。这里同时清空文件参数，避免
            # CLI 为一个不会被读取的文件执行路径解析、存在性检查或格式
            # 校验。
            params.bgm_file = ""
        elif not params.bgm_file:
            # 缺少文件是否构成错误取决于通用 BGM 开关，不能在 argparse 阶段
            # 无条件拦截，否则 ``custom + 0%`` 会和 WebUI、服务层行为不一致。
            raise ValueError("se requiere --bgm-file cuando --bgm-type es custom")
        else:
            try:
                # CLI、WebUI 和任务服务必须共用同一个 BGM 文件边界。这里直接
                # 复用服务层解析，既支持用户上传目录和内置歌曲目录，也
                # 自动继承新增音频格式及路径安全规则，避免多个入口分别
                # 维护白名单。
                params.bgm_file = bgm_service.resolve_bgm_file(params.bgm_file)
            except ValueError as exc:
                supported_extensions = ", ".join(
                    bgm_service.SUPPORTED_BGM_EXTENSIONS
                )
                raise ValueError(
                    "la música de fondo debe ser un archivo de audio admitido dentro de "
                    f"storage/bgm o resource/songs ({supported_extensions}): "
                    f"{params.bgm_file}"
                ) from exc

    if params.subtitle_enabled and params.font_name and stop_at == "video":
        font_path = _resolve_managed_resource_file(
            params.font_name,
            resource_dir=utils.font_dir(),
            description="fuente de subtítulos",
        )
        if not font_path.lower().endswith((".ttf", ".ttc")):
            raise ValueError("la fuente de subtítulos debe usar la extensión .ttf o .ttc")
        # 下游根据 resource/fonts 内的文件名拼接路径，因此仍保留纯文件名。
        params.font_name = os.path.basename(font_path)

    if params.video_source != "local" or stop_at not in {"materials", "video"}:
        return

    local_videos_dir = utils.storage_dir("local_videos", create=True)
    resolved_materials: list[tuple[MaterialInfo, str, str]] = []
    for material in params.video_materials or []:
        source_path = _resolve_cli_file(
            material.url,
            description="material local",
            fallback_dir=local_videos_dir,
        )
        extension = os.path.splitext(source_path)[1].lower()
        if extension not in local_material_extensions:
            allowed = ", ".join(sorted(local_material_extensions))
            raise ValueError(
                f"tipo de material local no admitido {extension or '<none>'}: "
                f"{material.url}; extensiones permitidas: {allowed}"
            )
        resolved_materials.append((material, source_path, extension))

    # 所有输入检查通过后再复制，避免第二个文件无效时留下第一个文件的
    # 孤儿副本。
    prepared_paths: dict[str, str] = {}
    for material, source_path, extension in resolved_materials:
        prepared_path = prepared_paths.get(source_path)
        if prepared_path is None:
            if _path_is_within_directory(source_path, local_videos_dir):
                prepared_path = source_path
            else:
                prepared_path = os.path.join(
                    local_videos_dir,
                    f"cli-material-{uuid4().hex}{extension}",
                )
                shutil.copy2(source_path, prepared_path)
                logger.info(
                    "material local CLI copiado al almacenamiento gestionado: "
                    f"origen={source_path}, destino={prepared_path}"
                )
            prepared_paths[source_path] = prepared_path

        material.url = prepared_path


def run_cli(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        params = build_video_params(args)
        prepare_cli_files(params, stop_at=args.stop_at)
    except (ValueError, OSError) as exc:
        logger.error(f"entrada CLI no válida: {exc}")
        return 2

    # 帮助参数会在 parse_args 中直接退出。把业务服务延迟到这里导入，
    # 保证 -h/--help 输出干净，同时不改变实际任务的初始化流程。
    from app.services import task as tm
    from app.utils import utils

    task_id = args.task_id or utils.get_uuid()
    logger.info(f"tarea CLI iniciada: task_id={task_id}, stop_at={args.stop_at}")
    try:
        result = tm.start(task_id=task_id, params=params, stop_at=args.stop_at)
    except Exception as exc:
        logger.exception(
            f"la tarea CLI falló con un error inesperado: task_id={task_id}, error={exc}"
        )
        return 1
    if not result or result.get("state") == tm.const.TASK_STATE_FAILED:
        failed_stage = result.get("failed_stage", "unknown") if result else "unknown"
        error = result.get("error", "unknown task error") if result else "empty result"
        logger.error(
            f"la tarea CLI falló: task_id={task_id}, stop_at={args.stop_at}, "
            f"stage={failed_stage}, error={error}"
        )
        return 1

    print(json.dumps({"task_id": task_id, "result": result}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(run_cli())
