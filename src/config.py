"""Configuration system for Roz.

Supports loading from:
- config.yaml for all settings
- Defaults for all values
"""

from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Dict, Any, Optional
import yaml


@dataclass
class LLMConfig:
    """LLM endpoint configuration."""
    endpoint: str = "http://localhost:8000"
    api_key: str = "default-key"
    model: str = "qwen-vision"
    timeout: int = 30  # seconds
    max_retries: int = 3


@dataclass
class LLMPromptConfig:
    """LLM prompt configuration for intelligent filtering."""
    change_detection_enabled: bool = True
    custom_prompt: Optional[str] = None  # Override default prompt via YAML
    sensitivity: str = "conservative"  # conservative, balanced, permissive


@dataclass
class MotionDetectionConfig:
    """Motion detection settings."""
    sensitivity: str = "medium"  # high, medium, low
    frame_check_interval_ms: int = 100
    min_contour_area: int = 500
    blur_kernel_size: int = 5
    threshold_delta: int = 25
    enable_morphology: bool = True  # Enable morphological filtering for noise reduction
    morphology_kernel_size: int = 3  # Size of morphological kernel
    min_motion_pixels: int = 50  # Minimum total motion pixels to trigger detection
    mask_regions: list = field(default_factory=list)  # List of [x, y, w, h] regions to ignore


@dataclass
class StorageConfig:
    """Storage and quota settings."""
    storage_threshold_gb: float = 8.0
    data_dir: str = "data"
    images_dir: str = "data/images"


@dataclass
class TTSConfig:
    """Text-to-speech settings."""
    enabled: bool = True
    volume: float = 1.0  # 0.0 to 1.0
    device: Optional[str] = None  # None for auto-discovery (Jabra)
    rate: float = 1.0  # Speech rate
    voice_model: str = "en_GB-alba-medium.onnx"  # Piper voice model path


@dataclass
class LoggingConfig:
    """Logging configuration."""
    enabled: bool = True
    log_dir: str = "logs"
    log_file: str = "logs/roz.log"
    level: str = "WARNING"  # Changed to WARNING for less verbose output
    max_bytes: int = 10485760  # 10MB
    backup_count: int = 5


@dataclass
class CalibrationConfig:
    """Calibration settings."""
    auto_calibrate_on_startup: bool = True
    frames_to_capture: int = 5
    confidence_threshold: float = 0.7


@dataclass
class Config:
    """Main configuration object."""
    llm: LLMConfig = field(default_factory=LLMConfig)
    llm_prompt: LLMPromptConfig = field(default_factory=LLMPromptConfig)
    motion: MotionDetectionConfig = field(default_factory=MotionDetectionConfig)
    storage: StorageConfig = field(default_factory=StorageConfig)
    tts: TTSConfig = field(default_factory=TTSConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    calibration: CalibrationConfig = field(default_factory=CalibrationConfig)

    # Additional settings
    server_host: str = "0.0.0.0"
    server_port: int = 8000
    debug: bool = False


class ConfigLoader:
    """Load and manage configuration from YAML files."""

    def __init__(self, config_file: str = "config.yaml"):
        self.config_file = Path(config_file)
        self.config: Optional[Config] = None

    def load(self) -> Config:
        """Load configuration from YAML, with defaults."""
        # Start with defaults
        config = Config()

        # Override from YAML file
        if self.config_file.exists():
            self._apply_yaml_overrides(config)

        # Ensure directories exist
        self._create_directories(config)

        self.config = config
        return config

    def _apply_yaml_overrides(self, config: Config) -> None:
        """Apply YAML file overrides."""
        try:
            with open(self.config_file) as f:
                yaml_config = yaml.safe_load(f) or {}

            # LLM settings
            if "llm" in yaml_config:
                llm_cfg = yaml_config["llm"]
                if "endpoint" in llm_cfg:
                    config.llm.endpoint = llm_cfg["endpoint"]
                if "api_key" in llm_cfg:
                    config.llm.api_key = llm_cfg["api_key"]
                if "model" in llm_cfg:
                    config.llm.model = llm_cfg["model"]
                if "timeout" in llm_cfg:
                    config.llm.timeout = llm_cfg["timeout"]
                if "max_retries" in llm_cfg:
                    config.llm.max_retries = llm_cfg["max_retries"]

            # LLM prompt settings
            if "llm_prompt" in yaml_config:
                llm_prompt_cfg = yaml_config["llm_prompt"]
                if "change_detection_enabled" in llm_prompt_cfg:
                    config.llm_prompt.change_detection_enabled = llm_prompt_cfg["change_detection_enabled"]
                if "custom_prompt" in llm_prompt_cfg:
                    config.llm_prompt.custom_prompt = llm_prompt_cfg["custom_prompt"]
                if "sensitivity" in llm_prompt_cfg:
                    config.llm_prompt.sensitivity = llm_prompt_cfg["sensitivity"]

            # Motion detection settings
            if "motion" in yaml_config:
                motion_cfg = yaml_config["motion"]
                if "sensitivity" in motion_cfg:
                    config.motion.sensitivity = motion_cfg["sensitivity"]
                if "frame_check_interval_ms" in motion_cfg:
                    config.motion.frame_check_interval_ms = motion_cfg["frame_check_interval_ms"]
                if "min_contour_area" in motion_cfg:
                    config.motion.min_contour_area = motion_cfg["min_contour_area"]
                if "blur_kernel_size" in motion_cfg:
                    config.motion.blur_kernel_size = motion_cfg["blur_kernel_size"]
                if "threshold_delta" in motion_cfg:
                    config.motion.threshold_delta = motion_cfg["threshold_delta"]
                if "enable_morphology" in motion_cfg:
                    config.motion.enable_morphology = motion_cfg["enable_morphology"]
                if "morphology_kernel_size" in motion_cfg:
                    config.motion.morphology_kernel_size = motion_cfg["morphology_kernel_size"]
                if "min_motion_pixels" in motion_cfg:
                    config.motion.min_motion_pixels = motion_cfg["min_motion_pixels"]
                if "mask_regions" in motion_cfg:
                    config.motion.mask_regions = motion_cfg["mask_regions"]

            # Storage settings
            if "storage" in yaml_config:
                storage_cfg = yaml_config["storage"]
                if "storage_threshold_gb" in storage_cfg:
                    config.storage.storage_threshold_gb = storage_cfg["storage_threshold_gb"]

            # TTS settings
            if "tts" in yaml_config:
                tts_cfg = yaml_config["tts"]
                if "enabled" in tts_cfg:
                    config.tts.enabled = tts_cfg["enabled"]
                if "volume" in tts_cfg:
                    config.tts.volume = tts_cfg["volume"]
                if "device" in tts_cfg:
                    config.tts.device = tts_cfg["device"]
                if "rate" in tts_cfg:
                    config.tts.rate = tts_cfg["rate"]
                if "voice_model" in tts_cfg:
                    config.tts.voice_model = tts_cfg["voice_model"]

            # Server settings
            if "server" in yaml_config:
                server_cfg = yaml_config["server"]
                if "host" in server_cfg:
                    config.server_host = server_cfg["host"]
                if "port" in server_cfg:
                    config.server_port = server_cfg["port"]
                if "debug" in server_cfg:
                    config.debug = server_cfg["debug"]

        except yaml.YAMLError as e:
            print(f"Error parsing YAML config: {e}")

    def _create_directories(self, config: Config) -> None:
        """Ensure required directories exist."""
        Path(config.storage.data_dir).mkdir(parents=True, exist_ok=True)
        Path(config.storage.images_dir).mkdir(parents=True, exist_ok=True)
        Path(config.logging.log_dir).mkdir(parents=True, exist_ok=True)

    def save(self, config: Config, output_file: Optional[str] = None) -> None:
        """Save current configuration to YAML file."""
        output_path = Path(output_file or self.config_file)

        yaml_dict = {
            "llm": asdict(config.llm),
            "llm_prompt": asdict(config.llm_prompt),
            "motion": asdict(config.motion),
            "storage": asdict(config.storage),
            "tts": asdict(config.tts),
            "logging": asdict(config.logging),
            "calibration": asdict(config.calibration),
            "server": {
                "host": config.server_host,
                "port": config.server_port,
                "debug": config.debug,
            }
        }

        with open(output_path, "w") as f:
            yaml.dump(yaml_dict, f, default_flow_style=False)

    def get(self) -> Config:
        """Get loaded configuration."""
        if self.config is None:
            raise RuntimeError("Configuration not loaded. Call load() first.")
        return self.config


# Global config instance
_config_loader: Optional[ConfigLoader] = None


def init_config(config_file: str = "config.yaml") -> Config:
    """Initialize global configuration."""
    global _config_loader
    _config_loader = ConfigLoader(config_file)
    return _config_loader.load()


def get_config() -> Config:
    """Get current configuration."""
    if _config_loader is None:
        raise RuntimeError("Configuration not initialized. Call init_config() first.")
    return _config_loader.get()
