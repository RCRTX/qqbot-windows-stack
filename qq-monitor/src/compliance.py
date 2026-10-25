"""QQ bot stack component."""




import json
import os
import re
import time
import threading
import traceback
from collections import deque
from datetime import datetime
from typing import Dict, Any, List, Optional, Callable

from openai import OpenAI

from .logger import setup_logger
from .net_utils import normalize_localhost

logger = setup_logger("ai_review")

VIOLATION_CATEGORIES = {
    "fraud_ad": "诈骗广告/引流推广",
    "illegal_trade": "违法交易",
    "pornographic": "色情低俗",
    "violence_threat": "暴力威胁",
    "personal_attack": "人身攻击",
    "privacy": "隐私泄露",
    "minor_risk": "未成年人风险",
    "political": "政治敏感",
    "gambling": "赌博博彩",
    "spam": "恶意刷屏",
    "other": "其他风险"
}

SECONDARY_STATUS_LABELS = {
    "confirmed": "二次复核确认违规",
    "suspected": "二次复核疑似违规",
    "likely_false_positive": "二次复核可能误报",
    "secondary_unavailable": "二次复核不可用",
    "not_reviewed": "未二次复核"
}



SEVERITY_RANK = {"low": 0, "medium": 1, "high": 2, "critical": 3}
SECONDARY_STATUS_RANK = {
    "not_reviewed": 0,
    "secondary_unavailable": 0,
    "suspected": 1,
    "confirmed": 2,
}



def _repair_json_text(text: str) -> str:
    """QQ bot stack component."""
    s = (text or "").strip().lstrip("\ufeff")
    s = re.sub(r'^```(?:json)?\s*', '', s)
    s = re.sub(r'\s*```$', '', s)
    out, in_str, esc = [], False, False
    for ch in s:
        if esc:
            out.append(ch)
            esc = False
            continue
        if ch == "\\":
            out.append(ch)
            esc = True
            continue
        if ch == '"':
            in_str = not in_str
            out.append(ch)
            continue
        if in_str and ch == "\n":
            out.append("\\n")
            continue
        if in_str and ch == "\r":
            out.append("\\r")
            continue
        if in_str and ch == "\t":
            out.append("\\t")
            continue
        out.append(ch)
    s = "".join(out)
    s = re.sub(r',\s*([}\]])', r'\1', s)
    return s


def _salvage_json_fields(text: str, allowed_status=None) -> Dict[str, Any]:
    """QQ bot stack component."""
    allowed = allowed_status or {}
    fields: Dict[str, Any] = {}
    for key in ("status", "category", "severity", "reason", "content_preview"):
        m = re.search(r'"%s"\s*:\s*"((?:[^"\\]|\\.)*)' % key, text or "", re.DOTALL)
        if not m:
            continue
        val = m.group(1)
        val = val.replace('\\n', ' ').replace('\\r', ' ').replace('\\"', '"').replace('\\t', ' ')
        fields[key] = val.strip()[:500]
    if allowed and fields.get("status") not in allowed:
        return {}
    if not allowed and not fields.get("status"):
        return {}
    return fields


class ViolationDetector:
    """QQ bot stack component."""

    def __init__(self, keywords_file: str, banned_words_file: str,
                 whitelist_users: List[int] = None):
        self.keywords_file = keywords_file
        self.banned_words_file = banned_words_file
        self.whitelist_users = set(whitelist_users or [])

        self._keywords: List[str] = []
        self._keyword_patterns: List[re.Pattern] = []
        self._banned_words: List[str] = []

        self._load_rules()

    def _load_rules(self) -> None:
        """QQ bot stack component."""
        self._keywords = []
        self._keyword_patterns = []
        self._banned_words = []

        
        if os.path.exists(self.keywords_file):
            with open(self.keywords_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    
                    if line.startswith("/") and line.endswith("/"):
                        pattern = line[1:-1]
                        try:
                            self._keyword_patterns.append(re.compile(pattern, re.IGNORECASE))
                        except re.error:
                            logger.warning(f"无效的正则表达式: {line}")
                    else:
                        self._keywords.append(line.lower())

        
        if os.path.exists(self.banned_words_file):
            with open(self.banned_words_file, 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    self._banned_words.append(line.lower())

        logger.info(f"已加载 {len(self._keywords)} 个关键词, "
                    f"{len(self._keyword_patterns)} 个正则规则, "
                    f"{len(self._banned_words)} 个禁言词")

    def reload_rules(self) -> None:
        """QQ bot stack component."""
        self._load_rules()
        logger.info("规则文件已重新加载")

    def check_message(self, message: Dict[str, Any]) -> Optional[Dict]:
        """QQ bot stack component."""





        user_id = message.get("user_id", 0)
        if user_id in self.whitelist_users:
            return None

        text = message.get("content", {}).get("text", "").lower()

        
        for word in self._banned_words:
            if word in text:
                return {
                    "type": "keyword_violation",
                    "severity": "high",
                    "category": "other",
                    "category_label": VIOLATION_CATEGORIES["other"],
                    "violation_type": "禁言词命中",
                    "rule_type": "banned_word",
                    "matched_word": word,
                    "message": message
                }

        
        for keyword in self._keywords:
            if keyword in text:
                return {
                    "type": "keyword_violation",
                    "severity": "medium",
                    "category": "other",
                    "category_label": VIOLATION_CATEGORIES["other"],
                    "violation_type": "关键词命中",
                    "rule_type": "keyword",
                    "matched_word": keyword,
                    "message": message
                }

        
        for pattern in self._keyword_patterns:
            match = pattern.search(text)
            if match:
                return {
                    "type": "keyword_violation",
                    "severity": "medium",
                    "category": "other",
                    "category_label": VIOLATION_CATEGORIES["other"],
                    "violation_type": "正则规则命中",
                    "rule_type": "regex",
                    "matched_word": match.group(),
                    "message": message
                }

        return None

    def check_messages_batch(self, messages: List[Dict]) -> List[Dict]:
        """QQ bot stack component."""
        violations = []
        for msg in messages:
            result = self.check_message(msg)
            if result:
                violations.append(result)
        return violations


class AIReviewer:
    """QQ bot stack component."""

    def __init__(self, api_base: str, api_key: str, model: str,
                 system_prompt: str, max_messages_per_review: int = 100,
                 context_before_messages: int = 3,
                 context_after_messages: int = 2,
                 secondary_review_enabled: bool = True,
                 secondary_api_base: str = None,
                 secondary_api_key: str = None,
                 secondary_model: str = None,
                 secondary_system_prompt: str = None):
        self.api_base = self._fix_localhost(api_base)
        self.secondary_api_base = self._fix_localhost(secondary_api_base) if secondary_api_base else None
        self.api_key = api_key
        self.model = model
        self.system_prompt = system_prompt
        self.max_messages_per_review = max_messages_per_review
        self.context_before_messages = max(0, int(context_before_messages or 0))
        self.context_after_messages = max(0, int(context_after_messages or 0))
        self.secondary_review_enabled = secondary_review_enabled
        self.secondary_api_key = secondary_api_key or api_key
        self.secondary_model = secondary_model or model
        self.secondary_system_prompt = secondary_system_prompt or "你是严格、谨慎、低误报的QQ群聊合规二次复核员。必须只输出JSON。"
        if not self.secondary_api_base:
            self.secondary_api_base = self.api_base
        self._last_review_time = 0
        self._is_reviewing = False
        self._last_error = ""
        self._last_result = {
            "review_time": "",
            "reviewed_count": 0,
            "violation_count": 0,
            "error": ""
        }

        self._client = None
        self._secondary_client = None
        self._init_client()
        self._init_secondary_client()

    @staticmethod
    def _fix_localhost(url: str) -> str:
        """QQ bot stack component."""
        return normalize_localhost(url)

    def _init_client(self) -> None:
        """QQ bot stack component."""
        try:
            self._client = OpenAI(
                base_url=self.api_base,
                api_key=self.api_key,
                timeout=60
            )
            logger.info(f"AI客户端初始化: base={self.api_base}, model={self.model}")
        except Exception as e:
            logger.error(f"AI客户端初始化失败: {e}")
            self._client = None

    def _init_secondary_client(self) -> None:
        """QQ bot stack component."""
        try:
            self._secondary_client = OpenAI(
                base_url=self.secondary_api_base,
                api_key=self.secondary_api_key,
                timeout=60
            )
            logger.info(f"二次审核AI客户端初始化: base={self.secondary_api_base}, model={self.secondary_model}")
        except Exception as e:
            logger.error(f"二次审核AI客户端初始化失败: {e}")
            self._secondary_client = None

    def reload_config(self, api_base: str = None, api_key: str = None,
                      model: str = None, system_prompt: str = None,
                      context_before_messages: int = None,
                      context_after_messages: int = None,
                      secondary_review_enabled: bool = None,
                      secondary_api_base: str = None,
                      secondary_api_key: str = None,
                      secondary_model: str = None,
                      secondary_system_prompt: str = None) -> bool:
        """QQ bot stack component."""
        changed = False
        if api_base is not None and api_base != self.api_base:
            self.api_base = api_base
            changed = True
        if api_key is not None and api_key != self.api_key:
            self.api_key = api_key
            changed = True
        if model is not None and model != self.model:
            self.model = model
            changed = True
        if system_prompt is not None and system_prompt != self.system_prompt:
            self.system_prompt = system_prompt
            changed = True
        if context_before_messages is not None:
            self.context_before_messages = max(0, int(context_before_messages))
        if context_after_messages is not None:
            self.context_after_messages = max(0, int(context_after_messages))
        if secondary_review_enabled is not None:
            self.secondary_review_enabled = secondary_review_enabled
        secondary_changed = False
        if secondary_api_base is not None and secondary_api_base != self.secondary_api_base:
            self.secondary_api_base = secondary_api_base
            secondary_changed = True
        if secondary_api_key is not None and secondary_api_key != self.secondary_api_key:
            self.secondary_api_key = secondary_api_key
            secondary_changed = True
        if secondary_model is not None and secondary_model != self.secondary_model:
            self.secondary_model = secondary_model
            secondary_changed = True
        if secondary_system_prompt is not None and secondary_system_prompt != self.secondary_system_prompt:
            self.secondary_system_prompt = secondary_system_prompt

        if changed:
            self._init_client()
            logger.info(f"AI配置已更新: base={self.api_base}, model={self.model}")
        if secondary_changed:
            self._init_secondary_client()
            logger.info(f"二次审核AI配置已更新: base={self.secondary_api_base}, model={self.secondary_model}")
        return changed

    def test_connection(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        result = {"success": False, "error": "", "model": self.model, "base": self.api_base}
        if not self._client:
            result["error"] = "客户端未初始化"
            return result
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "你好，请回复\"连接成功\""}],
                temperature=0.3,
                max_tokens=50
            )
            answer = resp.choices[0].message.content.strip()
            result["success"] = True
            result["response"] = answer
        except Exception as e:
            result["error"] = str(e)
        return result

    def test_secondary_connection(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        result = {
            "success": False,
            "error": "",
            "model": self.secondary_model,
            "base": self.secondary_api_base
        }
        if not self._secondary_client:
            result["error"] = "二次审核AI客户端未初始化"
            return result
        try:
            resp = self._secondary_client.chat.completions.create(
                model=self.secondary_model,
                messages=[{"role": "user", "content": "你好，请回复\"二次审核连接成功\""}],
                temperature=0.2,
                max_tokens=50
            )
            result["success"] = True
            result["response"] = resp.choices[0].message.content.strip()
        except Exception as e:
            result["error"] = str(e)
        return result

    def review_messages(self, messages: List[Dict[str, Any]]) -> List[Dict]:
        """QQ bot stack component."""





        review_items = self._build_context_review_items(messages)
        if not review_items:
            self._last_result = {
                "review_time": datetime.now().isoformat(),
                "reviewed_count": 0,
                "violation_count": 0,
                "error": ""
            }
            return []

        self._last_error = ""

        if not self._client:
            self._last_error = "AI客户端未初始化"
            logger.error(f"AI审查失败: {self._last_error}")
            return []

        if self._is_reviewing:
            self._last_error = "AI审查正在进行中"
            logger.info("AI审查正在进行中，跳过本次审查")
            return []

        self._is_reviewing = True
        violations = []

        try:
            
            review_text = self._build_review_text(review_items)

            
            
            
            prompt = f"""请审查以下QQ群聊记录，判断是否存在违规内容。
审查时必须结合“目标消息”的上文和下文，识别多条消息组合后才成立的风险，例如拆分广告、连续引流、上下文人身攻击、前后文隐私泄露、前后呼应的违法交易等。
只有目标消息可以作为违规结果输出；上下文消息只用于辅助理解，除非它本身也是另一个目标消息。

标准违规分类只能使用这些category值：
- fraud_ad：诈骗广告/引流推广
- illegal_trade：违法交易
- pornographic：色情低俗
- violence_threat：暴力威胁
- personal_attack：人身攻击
- privacy：隐私泄露
- minor_risk：未成年人风险
- political：政治敏感
- gambling：赌博博彩
- spam：恶意刷屏
- other：其他风险

## 聊天记录
{review_text}

## 输出要求
请严格按以下JSON格式输出（不要输出其他内容）：
message_index 必须填写“[目标消息 N]”中的 N，数字从0开始。不要填写上文/下文的序号或原始消息序号。
```json
{{
    "has_violation": true/false,
    "violations": [
        {{
            "message_index": 0,
            "severity": "low/medium/high/critical",
            "category": "fraud_ad/illegal_trade/pornographic/violence_threat/personal_attack/privacy/minor_risk/political/gambling/spam/other",
            "type": "违规类型（如：色情/暴力/广告/人身攻击/政治敏感/其他）",
            "reason": "判定理由",
            "content_preview": "违规内容摘要"
        }}
    ],
    "summary": "整体审查总结"
}}
```"""

            logger.info(f"开始AI审查，共 {len(review_items)} 条目标消息，上文{self.context_before_messages}条，下文{self.context_after_messages}条")

            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3,
                max_tokens=2000
            )

            result_text = response.choices[0].message.content.strip()
            violations = self._parse_ai_response(result_text, review_items)
            if self.secondary_review_enabled and violations:
                violations = self._secondary_review_violations(violations)

            self._last_review_time = time.time()
            self._last_result = {
                "review_time": datetime.now().isoformat(),
                "reviewed_count": len(review_items),
                "violation_count": len(violations),
                "error": ""
            }
            logger.info(f"AI审查完成，发现 {len(violations)} 条违规")

        except Exception as e:
            self._last_error = str(e)
            self._last_result = {
                "review_time": datetime.now().isoformat(),
                "reviewed_count": len(review_items),
                "violation_count": 0,
                "error": self._last_error
            }
            logger.error(f"AI审查失败: {e}")
        finally:
            self._is_reviewing = False

        return violations

    def _normalize_category(self, category: str, violation_type: str = "") -> str:
        """QQ bot stack component."""
        raw = str(category or "").strip()
        if raw in VIOLATION_CATEGORIES:
            return raw

        text = f"{raw} {violation_type}".lower()
        mapping = [
            ("fraud_ad", ["诈骗", "广告", "引流", "推广", "钓鱼", "刷单"]),
            ("illegal_trade", ["违法", "交易", "假证", "发票", "毒", "枪", "买卖"]),
            ("pornographic", ["色情", "低俗", "成人", "裸", "约炮"]),
            ("violence_threat", ["暴力", "威胁", "杀", "打死", "人身安全"]),
            ("personal_attack", ["人身攻击", "辱骂", "攻击", "歧视"]),
            ("privacy", ["隐私", "手机号", "身份证", "住址", "泄露"]),
            ("minor_risk", ["未成年", "未成年人", "儿童", "学生"]),
            ("political", ["政治", "敏感"]),
            ("gambling", ["赌博", "博彩", "赌场", "下注"]),
            ("spam", ["刷屏", "轰炸", "重复"])
        ]
        for key, words in mapping:
            if any(word in text for word in words):
                return key
        return "other"

    def _secondary_review_violations(self, violations: List[Dict]) -> List[Dict]:
        """QQ bot stack component."""
        reviewed = []
        for violation in violations:
            try:
                reviewed.append(self._secondary_review_one(violation))
            except Exception as e:
                logger.error(f"二次AI审查失败，保留首次结果: {e}")
                violation["secondary_status"] = "secondary_unavailable"
                violation["secondary_status_label"] = SECONDARY_STATUS_LABELS["secondary_unavailable"]
                violation["secondary_reason"] = f"二次审查失败，功能已降级；按首次AI结果上报。错误: {e}"
                violation["report_basis"] = "secondary_failed_use_primary"
                violation["report_basis_label"] = "二次复核不可用，按首次AI结果上报"
                violation["should_notify"] = True
                reviewed.append(violation)
        return reviewed

    def _secondary_review_one(self, violation: Dict) -> Dict:
        """QQ bot stack component."""
        if not self._secondary_client:
            raise RuntimeError("二次审核AI客户端未初始化")

        msg = violation.get("message", {})
        text = self._extract_review_text(msg)
        category_list = "\n".join(
            f"- {key}: {label}" for key, label in VIOLATION_CATEGORIES.items()
        )
        prompt = f"""你是QQ群聊违规审查的二次复核员。请只复核下面这条"首次AI认为违规"的消息。

要求：
1. 仔细审查消息内容，结合上下文判断是否真的存在风险。
2. 如果首次审查的证据充分、分类准确，status=confirmed，并保留或修正为更准确的category。
3. 如果有风险但证据不够完整，status=suspected，并给出你认为最准确的category。
4. 只有在首次审查明显误判（如把普通闲聊、玩笑、纯表情/图片占位判为违规）时，status=likely_false_positive。
5. 不要因为"语气不严重"就把真正的违规降级为other或low；分类和严重程度应基于内容本身的风险。
6. 必须给出标准category，且只能从下列值选择：
{category_list}

消息信息：
群号：{msg.get("group_id", "")}
用户：{msg.get("card") or msg.get("nickname", "")}（QQ:{msg.get("user_id", "")}）
时间：{msg.get("datetime", "")}
消息内容：{text}

首次审查结果：
严重程度：{violation.get("severity", "")}
分类：{violation.get("category", "")} {violation.get("category_label", "")}
违规类型：{violation.get("violation_type", "")}
理由：{violation.get("reason", "")}

请严格只输出JSON：
{{
    "status": "confirmed/suspected/likely_false_positive",
    "category": "fraud_ad/illegal_trade/pornographic/violence_threat/personal_attack/privacy/minor_risk/political/gambling/spam/other",
    "severity": "low/medium/high/critical",
    "reason": "二次复核理由",
    "content_preview": "证据片段或内容摘要"
}}"""
        response = self._secondary_client.chat.completions.create(
            model=self.secondary_model,
            messages=[
                {"role": "system", "content": self.secondary_system_prompt},
                {"role": "user", "content": prompt}
            ],
            temperature=0.1,
            
            
            max_tokens=2048
        )
        result_text = response.choices[0].message.content.strip()
        data = self._load_json_from_ai_text(result_text)
        status = data.get("status", "suspected")
        if status not in SECONDARY_STATUS_LABELS:
            status = "suspected"

        
        secondary_category = self._normalize_category(data.get("category"), violation.get("violation_type", ""))
        if status == "confirmed":
            category = secondary_category
        elif status == "suspected":
            
            if secondary_category != "other" or violation.get("category") == "other":
                category = secondary_category
            else:
                category = violation.get("category", secondary_category)
        else:
            
            category = violation.get("category", secondary_category)

        violation["secondary_status"] = status
        violation["secondary_status_label"] = SECONDARY_STATUS_LABELS[status]
        violation["secondary_reason"] = data.get("reason", "")

        
        if status == "likely_false_positive":
            violation["report_basis"] = "secondary_false_positive_keep_primary"
            violation["report_basis_label"] = "二次复核判定误报，保留首次记录但不通知"
        else:
            violation["report_basis"] = "secondary_review"
            violation["report_basis_label"] = "按二次复核结果上报"

        violation["category"] = category
        violation["category_label"] = VIOLATION_CATEGORIES[category]

        
        if status == "confirmed":
            violation["severity"] = data.get("severity") or violation.get("severity", "medium")
        elif status == "suspected":
            primary_sev = violation.get("severity", "medium")
            secondary_sev = data.get("severity", "medium")
            severity_order = {"low": 0, "medium": 1, "high": 2, "critical": 3}
            if severity_order.get(secondary_sev, 1) > severity_order.get(primary_sev, 1):
                violation["severity"] = secondary_sev
        

        violation["content_preview"] = data.get("content_preview") or violation.get("content_preview", "")
        violation["should_notify"] = status != "likely_false_positive"
        return violation

    def _load_json_from_ai_text(self, response_text: str) -> Dict[str, Any]:
        """QQ bot stack component."""
        text = response_text or ""
        json_match = re.search(r'```json\s*(.*?)\s*```', text, re.DOTALL)
        if json_match:
            json_str = json_match.group(1)
        else:
            json_match = re.search(r'\{.*\}', text, re.DOTALL)
            json_str = json_match.group(0) if json_match else text

        errors = []
        for candidate in (json_str, _repair_json_text(json_str)):
            try:
                return json.loads(candidate)
            except (json.JSONDecodeError, TypeError) as e:
                errors.append(e)
        
        salvaged = _salvage_json_fields(json_str, SECONDARY_STATUS_LABELS)
        if salvaged:
            logger.warning("二次AI审查 JSON 不完整，已从文本中抠出关键字段: %s",
                           sorted(salvaged.keys()))
            return salvaged
        raise errors[-1] if errors else ValueError("AI 未返回可解析的 JSON")

    def _build_context_review_items(self, messages: List[Dict]) -> List[Dict[str, Any]]:
        """QQ bot stack component."""
        reviewable_indexes = [
            i for i, msg in enumerate(messages)
            if msg.get("type") == "message" and self._extract_review_text(msg)
        ]
        items = []
        for item_index, msg_index in enumerate(reviewable_indexes):
            start = max(0, msg_index - self.context_before_messages)
            end = min(len(messages), msg_index + self.context_after_messages + 1)
            context = []
            for i in range(start, end):
                msg = messages[i]
                if msg.get("type") != "message":
                    continue
                text = self._extract_review_text(msg)
                if not text:
                    continue
                context.append({
                    "relative": "目标" if i == msg_index else ("上文" if i < msg_index else "下文"),
                    "message": msg,
                    "text": text
                })
            items.append({
                "message_index": msg_index,
                "message": messages[msg_index],
                "context": context,
                "review_index": item_index
            })
        return items

    def _build_review_text(self, review_items: List[Dict[str, Any]]) -> str:
        """QQ bot stack component."""
        lines = []
        for item in review_items:
            lines.append(f"\n[目标消息 {item['review_index']}]")
            for ctx in item.get("context", []):
                msg = ctx["message"]
                sender = msg.get("card") or msg.get("nickname", "未知用户")
                time_str = msg.get("datetime", "")
                label = ctx["relative"]
                marker = " <<<请审查这条>>>" if label == "目标" else ""
                lines.append(f"{label}: {time_str} {sender}(QQ:{msg.get('user_id', '')}): {ctx['text']}{marker}")

        return "\n".join(lines)

    def _extract_review_text(self, message: Dict[str, Any]) -> str:
        """QQ bot stack component."""
        content = message.get("content", {})
        segments = content.get("segments", [])
        text_parts = []

        for seg in segments:
            if seg.get("type") != "text":
                continue
            seg_data = seg.get("data", seg)
            text = seg.get("text", "") or seg_data.get("text", "")
            text = str(text).strip()
            if text:
                text_parts.append(text)

        if text_parts:
            return " ".join(text_parts).strip()

        fallback = str(content.get("text", "") or message.get("raw_message", "")).strip()
        if not fallback:
            return ""

        media_only_patterns = [
            r"\[包含\d+张图片\]",
            r"\[包含表情\]",
            r"\[图片\]",
            r"\[表情(?::[^\]]*)?\]",
            r"\[语音消息\]",
            r"\[视频\]",
            r"\[合并转发消息\]",
            r"\[JSON消息\]",
            r"\[XML消息\]",
            r"\[Markdown消息\]",
            r"\[CQ:[^\]]+\]"
        ]
        cleaned = fallback
        for pattern in media_only_patterns:
            cleaned = re.sub(pattern, " ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s+", " ", cleaned).strip()
        return cleaned

    @staticmethod
    def _coerce_index(value: Any) -> Optional[int]:
        """QQ bot stack component."""




        if value is None or isinstance(value, bool):
            return None
        if isinstance(value, int):
            return value
        try:
            return int(str(value).strip())
        except (TypeError, ValueError):
            return None

    def _match_review_item(self, preview: str,
                           review_items: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
        """QQ bot stack component."""
        preview = (preview or "").strip()
        if not preview:
            return None
        for item in review_items:
            text = self._extract_review_text(item.get("message", {}))
            if text and (preview in text or text in preview):
                return item
        return None

    def _parse_ai_response(self, response_text: str,
                           review_items: List[Dict[str, Any]]) -> List[Dict]:
        """QQ bot stack component."""
        violations = []

        try:
            result = self._load_json_from_ai_text(response_text)
        except json.JSONDecodeError as e:
            logger.error(f"解析AI响应JSON失败: {e}")
            logger.debug(f"AI原始响应: {response_text[:500]}")
            raise ValueError("AI审查返回无效JSON，保留待审消息") from e
        except Exception as e:
            logger.error(f"解析AI响应失败: {e}")
            raise ValueError("AI审查响应解析失败，保留待审消息") from e

        if not isinstance(result, dict) or not isinstance(result.get("has_violation"), bool):
            raise ValueError("AI审查响应缺少布尔字段 has_violation")
        if result["has_violation"] and not isinstance(result.get("violations"), list):
            raise ValueError("AI审查响应缺少违规列表")

        if not result.get("has_violation", False):
            return []

        for v in result.get("violations", []) or []:
            try:
                idx = self._coerce_index(v.get("message_index"))
                item = None
                if idx is not None:
                    if 0 <= idx < len(review_items):
                        item = review_items[idx]
                    elif 1 <= idx <= len(review_items):
                        item = review_items[idx - 1]  
                if item is None:
                    item = self._match_review_item(v.get("content_preview", ""), review_items)
                if item is None:
                    logger.warning(
                        f"AI返回的违规条目无法定位到目标消息，已跳过: "
                        f"message_index={v.get('message_index')!r}, "
                        f"preview={str(v.get('content_preview', ''))[:60]!r}"
                    )
                    continue

                original_msg = item.get("message", {})
                category = self._normalize_category(v.get("category"), v.get("type", ""))
                violations.append({
                    "type": "ai_violation",
                    "severity": v.get("severity", "medium"),
                    "category": category,
                    "category_label": VIOLATION_CATEGORIES[category],
                    "violation_type": v.get("type", "未知"),
                    "reason": v.get("reason", ""),
                    "content_preview": v.get("content_preview", ""),
                    "message": original_msg,
                    "context_messages": [
                        ctx.get("message", {}) for ctx in item.get("context", [])
                    ],
                    "context_before_messages": self.context_before_messages,
                    "context_after_messages": self.context_after_messages,
                    "ai_summary": result.get("summary", ""),
                    "secondary_status": "not_reviewed",
                    "secondary_status_label": SECONDARY_STATUS_LABELS["not_reviewed"],
                    "secondary_reason": "",
                    "report_basis": "primary_review",
                    "report_basis_label": "按首次AI结果上报",
                    "should_notify": True,
                    "review_time": datetime.now().isoformat()
                })
            except Exception as e:
                logger.error(f"处理单条AI违规结果失败，已跳过: {e}")
                continue

        return violations

    def get_status(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        return {
            "is_reviewing": self._is_reviewing,
            "last_error": self._last_error,
            "last_result": self._last_result,
            "last_review_time": self._last_review_time,
            "model": self.model,
            "api_base": self.api_base
        }


class ComplianceManager:
    """QQ bot stack component."""

    def __init__(self, config: Dict[str, Any], config_path: str = ""):
        self._config = config
        if config_path:
            self._config['_config_path'] = config_path

        rules_config = config.get("rules", {})
        ai_config = config.get("ai_review", {})
        secondary_config = config.get("secondary_ai_review", {})

        
        self.detector = ViolationDetector(
            keywords_file=rules_config.get("keywords_file", "./rules/keywords.txt"),
            banned_words_file=rules_config.get("banned_words_file", "./rules/banned_words.txt"),
            whitelist_users=rules_config.get("whitelist_users", [])
        )

        
        self.ai_reviewer = None
        if ai_config.get("enabled", False):
            try:
                self.ai_reviewer = AIReviewer(
                    api_base=ai_config.get("api_base", "http://localhost:11434/v1"),
                    api_key=ai_config.get("api_key", "ollama"),
                    model=ai_config.get("model", "qwen2.5"),
                    system_prompt=ai_config.get("system_prompt", ""),
                    max_messages_per_review=ai_config.get("max_messages_per_review", 100),
                    context_before_messages=ai_config.get("context_before_messages", 3),
                    context_after_messages=ai_config.get("context_after_messages", 2),
                    secondary_review_enabled=secondary_config.get("enabled", ai_config.get("secondary_review_enabled", True)),
                    secondary_api_base=secondary_config.get("api_base", ai_config.get("api_base", "http://localhost:11434/v1")),
                    secondary_api_key=secondary_config.get("api_key", ai_config.get("api_key", "ollama")),
                    secondary_model=secondary_config.get("model", ai_config.get("model", "qwen2.5")),
                    secondary_system_prompt=secondary_config.get("system_prompt", "")
                )
                logger.info("AI审查器初始化成功")
            except Exception as e:
                logger.error(f"AI审查器初始化失败: {e}")

        self.review_interval = ai_config.get("review_interval_minutes", 5)
        self.max_messages_per_review = ai_config.get("max_messages_per_review", 100)
        self.max_pending_messages = self.max_messages_per_review * 2
        self.alert_cooldown = rules_config.get("alert_cooldown_seconds", 300)

        
        self._pending_messages: List[Dict] = []
        self._pending_lock = threading.Lock()
        
        self._dropped_pending_count = 0
        self._last_drop_warn = 0.0

        
        self._alert_cooldowns: Dict[str, float] = {}

        
        
        self._max_alerted_ids = 20000
        self._alerted_levels: Dict[tuple, int] = {}
        self._alerted_order: deque = deque()
        self._alerted_lock = threading.Lock()

        
        self._violation_callbacks: List[Callable] = []

    def on_violation(self, callback: Callable) -> None:
        """QQ bot stack component."""
        self._violation_callbacks.append(callback)

    def add_message(self, message: Dict[str, Any]) -> Optional[Dict]:
        """QQ bot stack component."""





        if message.get("type") != "message":
            return None

        
        violation = self.detector.check_message(message)
        if violation:
            
            cooldown_key = f"{message.get('group_id')}_{message.get('user_id')}"
            if self._check_cooldown(cooldown_key):
                logger.info(f"关键词违规检测命中: {violation.get('matched_word')}")
                self._trigger_violation(violation)
                return violation

        
        if self.ai_reviewer and not self.ai_reviewer._extract_review_text(message):
            logger.debug("消息无可审查文字内容，跳过AI审查队列")
            return None

        
        with self._pending_lock:
            self._pending_messages.append(message)
            
            
            if len(self._pending_messages) > self.max_pending_messages:
                drop_count = len(self._pending_messages) - self.max_messages_per_review
                self._pending_messages = self._pending_messages[-self.max_messages_per_review:]
                self._dropped_pending_count += drop_count
                self._warn_dropped_pending(drop_count)

        return None

    def _warn_dropped_pending(self, drop_count: int) -> None:
        """QQ bot stack component."""
        now = time.time()
        if now - self._last_drop_warn < 300:
            return
        self._last_drop_warn = now
        logger.warning(
            f"待审查缓冲区已满，本次丢弃 {drop_count} 条尚未审查的消息"
            f"（累计丢弃 {self._dropped_pending_count} 条）。"
            f"常见原因是 AI 审查持续失败或消息量超过处理速度，请检查 AI 服务是否可用。"
        )

    def do_ai_review(self) -> List[Dict]:
        """QQ bot stack component."""
        if not self.ai_reviewer:
            logger.info("AI审查器未启用，跳过审查")
            return []

        with self._pending_lock:
            
            
            
            pending_total = len(self._pending_messages)
            messages = self._pending_messages[:self.max_messages_per_review]

        if not messages:
            logger.info("没有待审查消息，跳过AI审查")
            return []

        if pending_total > len(messages):
            logger.info(f"待审查 {pending_total} 条，本轮先审查最早的 {len(messages)} 条")

        violations = self.ai_reviewer.review_messages(messages)

        if self.ai_reviewer._last_error:
            logger.warning(f"AI审查未成功，保留 {len(messages)} 条待审查消息: {self.ai_reviewer._last_error}")
            return []

        with self._pending_lock:
            reviewed_ids = {
                msg.get("message_id")
                for msg in messages
                if msg.get("message_id")
            }
            if reviewed_ids:
                self._pending_messages = [
                    msg for msg in self._pending_messages
                    if msg.get("message_id") not in reviewed_ids
                ]
            else:
                del self._pending_messages[:len(messages)]

        for v in violations:
            self._trigger_violation(v)

        return violations

    def review_history_messages(self, message_store, group_id: int = None,
                                hours_back: int = 24, max_messages: int = 200) -> List[Dict]:
        """QQ bot stack component."""











        if not self.ai_reviewer:
            logger.info("AI审查器未启用，跳过历史消息审查")
            return []

        try:
            from datetime import datetime, timedelta
            
            end_time = datetime.now()
            start_time = end_time - timedelta(hours=hours_back)
            start_time_str = start_time.strftime("%Y-%m-%d %H:%M:%S")
            end_time_str = end_time.strftime("%Y-%m-%d %H:%M:%S")

            
            if not hasattr(message_store, 'query_messages'):
                logger.error("message_store没有query_messages方法")
                return []

            result = message_store.query_messages(
                group_id=group_id,
                start_time=start_time_str,
                end_time=end_time_str,
                page_size=max_messages
            )

            messages = result.get('messages', [])
            if not messages:
                logger.info(f"历史消息审查：{hours_back}小时内没有找到消息")
                return []

            logger.info(f"历史消息审查：从{hours_back}小时内的{result.get('total', 0)}条中抽取{len(messages)}条进行审查")

            
            violations = self.ai_reviewer.review_messages(messages)

            if self.ai_reviewer._last_error:
                logger.warning(f"历史消息审查失败: {self.ai_reviewer._last_error}")
                return []

            
            for v in violations:
                self._trigger_violation(v)

            logger.info(f"历史消息审查完成，发现 {len(violations)} 条违规")
            return violations

        except Exception as e:
            logger.error(f"历史消息审查异常: {e}\n{traceback.format_exc()}")
            return []

    @staticmethod
    def _violation_key(violation: Dict) -> Optional[tuple]:
        """QQ bot stack component."""
        msg = violation.get("message") or {}
        mid = msg.get("message_id")
        if not mid:
            return None
        return (msg.get("group_id"), mid)

    @staticmethod
    def _level_of(severity: Any, secondary_status: Any) -> int:
        """QQ bot stack component."""
        sev = str(severity or "medium").strip().lower()
        status = str(secondary_status or "not_reviewed").strip().lower()
        return SEVERITY_RANK.get(sev, 1) * 10 + SECONDARY_STATUS_RANK.get(status, 0)

    @classmethod
    def _violation_level(cls, violation: Dict) -> int:
        """QQ bot stack component."""
        return cls._level_of(violation.get("severity"), violation.get("secondary_status"))

    def _get_alerted_level(self, key: tuple) -> Optional[int]:
        """QQ bot stack component."""
        with self._alerted_lock:
            return self._alerted_levels.get(key)

    def _mark_alerted(self, key: tuple, level: int) -> None:
        """QQ bot stack component."""
        with self._alerted_lock:
            if key not in self._alerted_levels:
                self._alerted_order.append(key)
            self._alerted_levels[key] = max(level, self._alerted_levels.get(key, -1))
            while len(self._alerted_order) > self._max_alerted_ids:
                self._alerted_levels.pop(self._alerted_order.popleft(), None)

    def seed_alerted_messages(self, records) -> int:
        """QQ bot stack component."""




        added = 0
        with self._alerted_lock:
            for record in records or []:
                try:
                    group_id, message_id, severity, secondary_status = record
                except (TypeError, ValueError):
                    continue
                if not message_id:
                    continue
                key = (group_id, message_id)
                level = self._level_of(severity, secondary_status)
                if key not in self._alerted_levels:
                    self._alerted_order.append(key)
                    added += 1
                self._alerted_levels[key] = max(level, self._alerted_levels.get(key, -1))
            while len(self._alerted_order) > self._max_alerted_ids:
                self._alerted_levels.pop(self._alerted_order.popleft(), None)
        if added:
            logger.info(f"已载入 {added} 条历史告警消息用于去重（含级别，支持后续升级补发）")
        return added

    def _trigger_violation(self, violation: Dict) -> None:
        """QQ bot stack component."""





        if violation.get("should_notify", True):
            key = self._violation_key(violation)
            if key is not None:
                level = self._violation_level(violation)
                prev_level = self._get_alerted_level(key)
                if prev_level is not None and level <= prev_level:
                    logger.info(
                        f"该消息已按不低于当前级别告警过，跳过重复推送: "
                        f"群{key[0]} 消息{key[1]}（当前{level} ≤ 已通知{prev_level}）"
                    )
                    return
                if prev_level is not None:
                    violation["is_escalation"] = True
                    violation["previous_level"] = prev_level
                    logger.warning(
                        f"违规级别升级，补发通知: 群{key[0]} 消息{key[1]} "
                        f"（{prev_level} → {level}，"
                        f"严重程度 {violation.get('severity')}，"
                        f"二次复核 {violation.get('secondary_status_label', '')}）"
                    )
                self._mark_alerted(key, level)
        for callback in self._violation_callbacks:
            try:
                callback(violation)
            except Exception as e:
                logger.error(f"违规回调执行失败: {e}")

    def _check_cooldown(self, key: str) -> bool:
        """QQ bot stack component."""
        now = time.time()
        if key in self._alert_cooldowns:
            if now - self._alert_cooldowns[key] < self.alert_cooldown:
                return False
        self._alert_cooldowns[key] = now
        
        
        if len(self._alert_cooldowns) > 5000:
            self._prune_cooldowns(now)
        return True

    def _prune_cooldowns(self, now: float = None) -> int:
        """QQ bot stack component."""
        if now is None:
            now = time.time()
        expired = [k for k, ts in self._alert_cooldowns.items()
                   if now - ts >= self.alert_cooldown]
        for k in expired:
            self._alert_cooldowns.pop(k, None)
        
        if len(self._alert_cooldowns) > 5000:
            oldest = sorted(self._alert_cooldowns.items(), key=lambda kv: kv[1])
            for k, _ts in oldest[:len(oldest) // 2]:
                self._alert_cooldowns.pop(k, None)
        return len(expired)

    def get_pending_count(self) -> int:
        """QQ bot stack component."""
        with self._pending_lock:
            return len(self._pending_messages)

    def get_ai_status(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        status = {
            "enabled": bool(self.ai_reviewer),
            "pending_count": self.get_pending_count(),
            "dropped_pending_count": self._dropped_pending_count
        }
        if self.ai_reviewer:
            status.update(self.ai_reviewer.get_status())
        return status

    def update_ai_config(self, api_base: str = None, api_key: str = None,
                        model: str = None, system_prompt: str = None,
                        enabled: bool = None, review_interval: int = None,
                        context_before_messages: int = None,
                        context_after_messages: int = None,
                        secondary_review_enabled: bool = None,
                        history_review_enabled: bool = None,
                        history_review_interval_hours: int = None,
                        history_review_hours_back: int = None,
                        history_review_max_messages: int = None) -> Dict[str, Any]:
        """QQ bot stack component."""
        result = {"success": False, "message": ""}

        try:
            if enabled is not None:
                self._config['ai_review']['enabled'] = enabled

            if review_interval is not None:
                self._config['ai_review']['review_interval_minutes'] = review_interval
                self.review_interval = review_interval

            ai_cfg = self._config['ai_review']
            if api_base is not None:
                ai_cfg['api_base'] = api_base
            if api_key is not None:
                ai_cfg['api_key'] = api_key
            if model is not None:
                ai_cfg['model'] = model
            if system_prompt is not None:
                ai_cfg['system_prompt'] = system_prompt
            if context_before_messages is not None:
                ai_cfg['context_before_messages'] = max(0, int(context_before_messages))
            if context_after_messages is not None:
                ai_cfg['context_after_messages'] = max(0, int(context_after_messages))
            if secondary_review_enabled is not None:
                ai_cfg['secondary_review_enabled'] = secondary_review_enabled
            
            if history_review_enabled is not None:
                ai_cfg['history_review_enabled'] = history_review_enabled
            if history_review_interval_hours is not None:
                ai_cfg['history_review_interval_hours'] = max(1, int(history_review_interval_hours))
            if history_review_hours_back is not None:
                ai_cfg['history_review_hours_back'] = max(1, int(history_review_hours_back))
            if history_review_max_messages is not None:
                ai_cfg['history_review_max_messages'] = max(10, int(history_review_max_messages))

            if enabled is False:
                self.ai_reviewer = None
            elif enabled is True and not self.ai_reviewer:
                secondary_cfg = self._config.get("secondary_ai_review", {})
                self.ai_reviewer = AIReviewer(
                    api_base=ai_cfg.get("api_base", "http://localhost:11434/v1"),
                    api_key=ai_cfg.get("api_key", "ollama"),
                    model=ai_cfg.get("model", "qwen2.5"),
                    system_prompt=ai_cfg.get("system_prompt", ""),
                    max_messages_per_review=ai_cfg.get("max_messages_per_review", 100),
                    context_before_messages=ai_cfg.get("context_before_messages", 3),
                    context_after_messages=ai_cfg.get("context_after_messages", 2),
                    secondary_review_enabled=secondary_cfg.get("enabled", ai_cfg.get("secondary_review_enabled", True)),
                    secondary_api_base=secondary_cfg.get("api_base", ai_cfg.get("api_base", "http://localhost:11434/v1")),
                    secondary_api_key=secondary_cfg.get("api_key", ai_cfg.get("api_key", "ollama")),
                    secondary_model=secondary_cfg.get("model", ai_cfg.get("model", "qwen2.5")),
                    secondary_system_prompt=secondary_cfg.get("system_prompt", "")
                )

            if self.ai_reviewer:
                self.ai_reviewer.reload_config(
                    api_base=api_base,
                    api_key=api_key,
                    model=model,
                    system_prompt=system_prompt,
                    context_before_messages=ai_cfg.get("context_before_messages", 3),
                    context_after_messages=ai_cfg.get("context_after_messages", 2),
                    secondary_review_enabled=self._config.get("secondary_ai_review", {}).get("enabled", ai_cfg.get("secondary_review_enabled", True))
                )

            
            self._save_config()
            result["success"] = True
            result["message"] = "AI配置已更新"

        except Exception as e:
            result["message"] = f"更新失败: {e}"

        return result

    def get_ai_config(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        cfg = self._config.get('ai_review', {})
        return {
            "enabled": cfg.get('enabled', False),
            "api_base": cfg.get('api_base', ''),
            "api_key": cfg.get('api_key', ''),
            "model": cfg.get('model', ''),
            "system_prompt": cfg.get('system_prompt', ''),
            "review_interval_minutes": cfg.get('review_interval_minutes', 5),
            "max_messages_per_review": cfg.get('max_messages_per_review', 100),
            "context_before_messages": cfg.get('context_before_messages', 3),
            "context_after_messages": cfg.get('context_after_messages', 2),
            "secondary_review_enabled": cfg.get('secondary_review_enabled', True),
            "history_review_enabled": cfg.get('history_review_enabled', True),
            "history_review_interval_hours": cfg.get('history_review_interval_hours', 2),
            "history_review_hours_back": cfg.get('history_review_hours_back', 4),
            "history_review_max_messages": cfg.get('history_review_max_messages', 150)
        }

    def test_ai_connection(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        if not self.ai_reviewer:
            return {"success": False, "error": "AI审查器未启用"}
        return self.ai_reviewer.test_connection()

    def get_secondary_ai_config(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        ai_cfg = self._config.get('ai_review', {})
        cfg = self._config.get('secondary_ai_review', {})
        return {
            "enabled": cfg.get('enabled', ai_cfg.get('secondary_review_enabled', True)),
            "api_base": cfg.get('api_base', ai_cfg.get('api_base', '')),
            "api_key": cfg.get('api_key', ai_cfg.get('api_key', '')),
            "model": cfg.get('model', ai_cfg.get('model', '')),
            "system_prompt": cfg.get(
                'system_prompt',
                "你是严格、谨慎、低误报的QQ群聊合规二次复核员。必须只输出JSON。"
            )
        }

    def update_secondary_ai_config(self, enabled: bool = None, api_base: str = None,
                                   api_key: str = None, model: str = None,
                                   system_prompt: str = None) -> Dict[str, Any]:
        """QQ bot stack component."""
        result = {"success": False, "message": ""}
        try:
            cfg = self._config.setdefault('secondary_ai_review', {})
            if enabled is not None:
                cfg['enabled'] = enabled
            if api_base is not None:
                cfg['api_base'] = api_base
            if api_key is not None:
                cfg['api_key'] = api_key
            if model is not None:
                cfg['model'] = model
            if system_prompt is not None:
                cfg['system_prompt'] = system_prompt

            if self.ai_reviewer:
                self.ai_reviewer.reload_config(
                    secondary_review_enabled=cfg.get('enabled', True),
                    secondary_api_base=cfg.get('api_base', self.ai_reviewer.api_base),
                    secondary_api_key=cfg.get('api_key', self.ai_reviewer.api_key),
                    secondary_model=cfg.get('model', self.ai_reviewer.model),
                    secondary_system_prompt=cfg.get('system_prompt', self.ai_reviewer.secondary_system_prompt)
                )

            self._save_config()
            result["success"] = True
            result["message"] = "二次审核AI配置已更新"
        except Exception as e:
            result["message"] = f"更新失败: {e}"
        return result

    def test_secondary_ai_connection(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        if not self.ai_reviewer:
            return {"success": False, "error": "AI审查器未启用"}
        return self.ai_reviewer.test_secondary_connection()

    def _save_config(self) -> None:
        """QQ bot stack component."""
        config_path = self._config.get('_config_path', '')
        if not config_path:
            return
        try:
            save_data = {k: v for k, v in self._config.items() if not k.startswith('_')}
            with open(config_path, 'w', encoding='utf-8') as f:
                json.dump(save_data, f, ensure_ascii=False, indent=4)
            logger.info("配置已保存到文件")
        except Exception as e:
            logger.error(f"保存配置文件失败: {e}")


class ChatCompanion:
    """QQ bot stack component."""

    def __init__(self, api_base: str, api_key: str, model: str,
                 system_prompt: str = "",
                 bot_name: str = "小助手",
                 cooldown_seconds: int = 10):
        self.api_base = api_base.replace("//localhost:", "//127.0.0.1:") if api_base else api_base
        self.api_key = api_key
        self.model = model
        self.bot_name = bot_name
        self.cooldown_seconds = cooldown_seconds
        self.system_prompt = system_prompt or (
            f"你是群聊里的{bot_name}，性格活泼友好、幽默风趣。"
            "别人@你时你会积极回应，回答要简短有趣，不要超过100字。"
            "不要输出JSON，直接用自然语言回复。"
        )
        self._client = None
        self._last_reply_time: Dict[int, float] = {}  
        self._init_client()
        logger.warning(f"陪聊功能已初始化: bot_name={self.bot_name}, model={self.model}, base={self.api_base}, cooldown={self.cooldown_seconds}s")

    def _init_client(self) -> None:
        try:
            self._client = OpenAI(
                base_url=self.api_base,
                api_key=self.api_key,
                timeout=30
            )
            logger.info(f"陪聊AI初始化: base={self.api_base}, model={self.model}")
        except Exception as e:
            logger.error(f"陪聊AI初始化失败: {e}")
            self._client = None

    def _cooldown_free(self, group_id: int) -> bool:
        """QQ bot stack component."""
        now = time.time()
        last = self._last_reply_time.get(group_id, 0)
        return (now - last) >= self.cooldown_seconds

    def _cooldown_mark(self, group_id: int) -> None:
        """QQ bot stack component."""
        self._last_reply_time[group_id] = time.time()

    def _check_cooldown(self, group_id: int) -> bool:
        """QQ bot stack component."""
        if not self._cooldown_free(group_id):
            return False
        self._cooldown_mark(group_id)
        return True

    def is_mentioned(self, message: Dict[str, Any], bot_qq: str) -> bool:
        """QQ bot stack component."""
        segments = message.get("content", {}).get("segments", [])
        bot_qq_str = str(bot_qq)
        for seg in segments:
            if seg.get("type") == "at":
                
                qq = str(seg.get("data", {}).get("qq", "") or seg.get("qq", ""))
                if qq == bot_qq_str or qq == "all":
                    return True
        return False

    def generate_reply(self, message: Dict[str, Any],
                       recent_context: List[Dict] = None) -> Optional[str]:
        """QQ bot stack component."""
        if not self._client:
            logger.debug("陪聊：AI客户端未初始化")
            return None

        group_id = message.get("group_id", 0)
        
        
        
        
        if not self._cooldown_free(group_id):
            logger.debug(f"陪聊冷却中，跳过群 {group_id}")
            return None

        sender = message.get("card") or message.get("nickname", "未知用户")
        text = self._extract_text(message)
        logger.debug(f"陪聊调试：sender={sender}, text='{text}'")
        if not text:
            logger.debug("陪聊：提取到的文字为空，跳过")
            return None

        
        context_lines = []
        if recent_context:
            for ctx_msg in recent_context[-6:]:
                ctx_sender = ctx_msg.get("card") or ctx_msg.get("nickname", "未知")
                ctx_text = self._extract_text(ctx_msg)
                if ctx_text:
                    context_lines.append(f"{ctx_sender}: {ctx_text}")

        context_str = "\n".join(context_lines) if context_lines else "无"

        prompt = f"""群聊上下文（最近几条消息）：
{context_str}

{sender} @了你：{text}

请用简短有趣的方式回复{sender}，不要超过100字。不要输出JSON。"""

        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.8,
                max_tokens=200
            )
            reply = response.choices[0].message.content.strip()
            if reply:
                self._cooldown_mark(group_id)     
                logger.info(f"陪聊回复群 {group_id}: {reply[:50]}...")
                return reply
        except Exception as e:
            logger.debug(f"陪聊AI回复失败: {e}")

        logger.debug(f"陪聊：AI返回空回复，model={self.model}")
        return None

    def _extract_text(self, message: Dict[str, Any]) -> str:
        """QQ bot stack component."""
        segments = message.get("content", {}).get("segments", [])
        parts = []
        for seg in segments:
            if seg.get("type") == "text":
                
                text = seg.get("data", {}).get("text", "") or seg.get("text", "")
                if text:
                    parts.append(text.strip())
        return " ".join(parts).strip()

    def test_connection(self) -> Dict[str, Any]:
        """QQ bot stack component."""
        result = {"success": False, "error": "", "model": self.model, "base": self.api_base}
        if not self._client:
            result["error"] = "客户端未初始化"
            return result
        try:
            resp = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": "你好，请用一句话介绍你自己"}],
                temperature=0.8,
                max_tokens=100
            )
            result["success"] = True
            result["response"] = resp.choices[0].message.content.strip()
        except Exception as e:
            result["error"] = str(e)
        return result

    def reload_config(self, api_base: str = None, api_key: str = None,
                      model: str = None, system_prompt: str = None,
                      bot_name: str = None, cooldown_seconds: int = None) -> bool:
        """QQ bot stack component."""
        changed = False
        if api_base and api_base != self.api_base:
            self.api_base = api_base
            changed = True
        if api_key and api_key != self.api_key:
            self.api_key = api_key
            changed = True
        if model and model != self.model:
            self.model = model
            changed = True
        if system_prompt is not None and system_prompt != self.system_prompt:
            self.system_prompt = system_prompt
        if bot_name is not None and bot_name != self.bot_name:
            self.bot_name = bot_name
        if cooldown_seconds is not None and cooldown_seconds != self.cooldown_seconds:
            self.cooldown_seconds = cooldown_seconds
        if changed:
            self._init_client()
        return changed


class Repeater:
    """QQ bot stack component."""

    def __init__(self, cooldown_seconds: int = 1800, max_entries_per_group: int = 5000):
        self.cooldown_seconds = cooldown_seconds
        self.max_entries_per_group = max_entries_per_group
        
        self._groups: Dict[int, Dict[str, Dict]] = {}

    def _evict_if_needed(self, group: Dict[str, Dict]) -> None:
        """QQ bot stack component."""
        if len(group) <= self.max_entries_per_group:
            return
        overflow = len(group) - self.max_entries_per_group
        oldest = sorted(group.items(), key=lambda kv: kv[1].get("last_time", 0))[:overflow]
        for key, _value in oldest:
            group.pop(key, None)

    def check_and_repeat(self, message: Dict[str, Any]) -> Optional[int]:
        """QQ bot stack component."""







        if message.get("is_bot"):
            return None
        
        if self._has_at_segment(message):
            return None
        group_id = message.get("group_id", 0)
        if not group_id:
            return None

        user_id = message.get("user_id", 0)
        text = self._extract_text(message)
        if not text or len(text) > 500:
            return None
        
        if text.startswith("/"):
            return None

        now = time.time()

        
        if group_id not in self._groups:
            self._groups[group_id] = {}

        group = self._groups[group_id]

        
        expired = [k for k, v in group.items() if now - v.get("last_time", 0) > self.cooldown_seconds]
        for k in expired:
            del group[k]

        
        key = text.strip()

        if key not in group:
            group[key] = {"users": set(), "sent": False, "last_time": now}

        record = group[key]
        record["last_time"] = now
        record["users"].add(user_id)

        
        self._evict_if_needed(group)

        
        if len(record["users"]) >= 2 and not record["sent"]:
            record["sent"] = True
            logger.info(f"复读触发：群{group_id}，{len(record['users'])}人发送了'{text[:30]}'")
            return group_id

        return None

    def _extract_text(self, message: Dict[str, Any]) -> str:
        """QQ bot stack component."""
        segments = message.get("content", {}).get("segments", [])
        parts = []
        for seg in segments:
            if seg.get("type") == "text":
                text = seg.get("data", {}).get("text", "") or seg.get("text", "")
                if text:
                    parts.append(text.strip())
        return " ".join(parts).strip()

    @staticmethod
    def _has_at_segment(message: Dict[str, Any]) -> bool:
        """QQ bot stack component."""




        segments = message.get("content", {}).get("segments", []) or []
        return any(isinstance(seg, dict) and seg.get("type") == "at" for seg in segments)
