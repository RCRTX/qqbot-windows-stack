"""QQ bot stack component."""




import json
import os
import copy
from typing import Dict, Any, Optional, List


DEFAULT_CONFIG = {'napcat': {'ws_url': 'ws://localhost:3001', 'http_url': 'http://localhost:3000', 'token': '', 'monitor_groups': []}, 'storage': {'data_dir': './data', 'log_dir': './logs', 'export_dir': './聊天记录', 'max_storage_mb': 500, 'archive_days': 30, 'file_rotate_hours': 24, 'save_images': True, 'max_image_size_mb': 5, 'save_files': True, 'large_file_confirm_mb': 1024, 'max_alert_records': 1000, 'max_memory_index_per_group': 10000, 'max_saved_ids': 200000, 'max_finished_pending_records': 200, 'auto_cleanup_enabled': False}, 'ai_review': {'enabled': False, 'api_base': 'http://127.0.0.1:11434/v1', 'api_key': '', 'model': '', 'review_interval_minutes': 5, 'max_messages_per_review': 100, 'context_before_messages': 3, 'context_after_messages': 2, 'system_prompt': '只依据明确证据判断风险，证据不足不判违规，只输出约定的 JSON。'}, 'secondary_ai_review': {'enabled': False, 'api_base': 'http://127.0.0.1:11434/v1', 'api_key': '', 'model': '', 'system_prompt': '只依据明确证据判断风险，证据不足不判违规，只输出约定的 JSON。'}, 'alert': {'qq': {'enabled': False, 'recipient_user_ids': []}, 'email': {'enabled': False, 'smtp_host': 'smtp.qq.com', 'smtp_port': 465, 'smtp_user': '', 'smtp_password': '', 'sender': '', 'recipients': [], 'use_ssl': True}, 'push': {'enabled': False, 'serverchan': {'sendkey': '', 'api_url': 'https://sctapi.ftqq.com/{sendkey}.send'}, 'pushplus': {'token': '', 'api_url': 'http://www.pushplus.plus/send'}}}, 'rules': {'keywords_file': './rules/keywords.txt', 'banned_words_file': './rules/banned_words.txt', 'whitelist_users': [], 'alert_cooldown_seconds': 300}, 'web_panel': {'host': '127.0.0.1', 'port': 8080, 'access_token': ''}, 'chat_companion': {'enabled': False, 'api_base': '', 'api_key': '', 'model': '', 'system_prompt': '', 'bot_name': '小助手', 'cooldown_seconds': 30}, 'marked_users': {'enabled': False}, 'repeater': {'enabled': False}, 'poke': {'enabled': False, 'proactive': {'enabled': False}}}


def _deep_merge(base: Dict, override: Dict) -> Dict:
    """QQ bot stack component."""
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


class Config:
    """QQ bot stack component."""

    _instance: Optional['Config'] = None
    _config: Dict[str, Any] = {}

    def __new__(cls, config_path: str = None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, config_path: str = None):
        if not hasattr(self, "_config_path"):
            self._config_path = None
        if not self._config and config_path:
            self.load(config_path)

    def load(self, config_path: str) -> None:
        """QQ bot stack component."""
        if not os.path.exists(config_path):
            raise FileNotFoundError(f"配置文件不存在: {config_path}")

        with open(config_path, 'r', encoding='utf-8') as f:
            user_config = json.load(f)

        self._config = _deep_merge(DEFAULT_CONFIG, user_config)
        self._config_path = os.path.abspath(config_path)
        self._validate()
        self._resolve_paths()

    def load_from_dict(self, config_dict: Dict[str, Any]) -> None:
        """QQ bot stack component."""
        self._config = _deep_merge(DEFAULT_CONFIG, config_dict)
        self._validate()
        self._resolve_paths()

    def _validate(self) -> None:
        """QQ bot stack component."""
        
        if not self._config['napcat']['ws_url']:
            raise ValueError("napcat.ws_url 不能为空")
        if not self._config['napcat']['monitor_groups']:
            raise ValueError("napcat.monitor_groups 不能为空，请至少配置一个群号")

        
        if self._config['storage']['max_storage_mb'] < 10:
            raise ValueError("storage.max_storage_mb 不能小于10MB")
        if self._config['storage']['archive_days'] < 1:
            raise ValueError("storage.archive_days 不能小于1天")

        
        if self._config['ai_review']['enabled']:
            if not self._config['ai_review']['api_base']:
                raise ValueError("ai_review.api_base 不能为空")
            if not self._config['ai_review']['model']:
                raise ValueError("ai_review.model 不能为空")

        
        email_cfg = self._config['alert']['email']
        if email_cfg['enabled']:
            if not email_cfg['smtp_host']:
                raise ValueError("alert.email.smtp_host 不能为空")
            if not email_cfg['smtp_user']:
                raise ValueError("alert.email.smtp_user 不能为空")
            if not email_cfg['recipients']:
                raise ValueError("alert.email.recipients 不能为空")

    def _resolve_paths(self) -> None:
        """QQ bot stack component."""
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._config['storage']['data_dir'] = os.path.abspath(
            os.path.join(base_dir, self._config['storage']['data_dir'])
        )
        self._config['storage']['log_dir'] = os.path.abspath(
            os.path.join(base_dir, self._config['storage']['log_dir'])
        )
        self._config['storage']['export_dir'] = os.path.abspath(
            os.path.join(base_dir, self._config['storage']['export_dir'])
        )
        self._config['rules']['keywords_file'] = os.path.abspath(
            os.path.join(base_dir, self._config['rules']['keywords_file'])
        )
        self._config['rules']['banned_words_file'] = os.path.abspath(
            os.path.join(base_dir, self._config['rules']['banned_words_file'])
        )

    @property
    def napcat(self) -> Dict[str, Any]:
        return self._config['napcat']

    @property
    def storage(self) -> Dict[str, Any]:
        return self._config['storage']

    @property
    def ai_review(self) -> Dict[str, Any]:
        return self._config['ai_review']

    @property
    def alert(self) -> Dict[str, Any]:
        return self._config['alert']

    @property
    def rules(self) -> Dict[str, Any]:
        return self._config['rules']

    def get(self, key: str, default=None) -> Any:
        """QQ bot stack component."""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict) and k in value:
                value = value[k]
            else:
                return default
        return value

    def reload(self, config_path: str = None) -> None:
        """QQ bot stack component."""
        if config_path is None:
            config_path = getattr(self, "_config_path", None)
        if not config_path:
            raise ValueError("未指定配置文件路径，无法重新加载配置")
        self.load(config_path)

    @property
    def config_path(self) -> Optional[str]:
        """QQ bot stack component."""
        return getattr(self, "_config_path", None)

    @classmethod
    def reset(cls):
        """QQ bot stack component."""
        cls._instance = None
        cls._config = {}
