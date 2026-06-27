import os


def _load_dotenv_if_exists() -> None:
    """轻量读取项目根目录 .env，避免额外依赖。系统环境变量优先。"""
    base = os.path.abspath(os.path.dirname(__file__))
    env_path = os.path.join(base, ".env")
    if not os.path.exists(env_path):
        return
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = value
    except Exception:
        pass


_load_dotenv_if_exists()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
DATABASE_DIR = os.path.join(BASE_DIR, "database")
UPLOAD_DIR = os.path.join(BASE_DIR, "uploads")
EXPORT_DIR = os.path.join(BASE_DIR, "exports")
DB_PATH = os.path.join(DATABASE_DIR, "vehicle.db")

SECRET_KEY = os.environ.get("SECRET_KEY", "change-this-secret-key")

# Odometer and risk-control settings
ODO_ROLLOVER = 1_000_000
MAX_SINGLE_TRIP_KM = 2000

# OCR settings
OCR_CONFIDENCE_THRESHOLD = 0.35
ALLOW_MANUAL_OVERRIDE = True

# V8.0: 不再内置默认账号。首次启动必须由管理员自己设置账号和密码。
DEFAULT_USERS = []

# 仅用于识别旧版包/旧数据库中的默认管理员密码，发现后会强制进入管理员初始化页面。
LEGACY_DEFAULT_ADMIN_USERNAME = "admin"
LEGACY_DEFAULT_ADMIN_PASSWORD = "admin123"

# V7 OCR settings
DEFAULT_PLATE_PROVINCE = os.environ.get("DEFAULT_PLATE_PROVINCE", "贵")
OCR_USE_GPU = os.environ.get("OCR_USE_GPU", "0") == "1"
OCR_DEBUG_CROPS = os.environ.get("OCR_DEBUG_CROPS", "0") == "1"
OCR_MAX_IMAGE_WIDTH = int(os.environ.get("OCR_MAX_IMAGE_WIDTH", "1100"))

# V8.3 OCR speed settings
# fast：只识别关键裁剪区域，默认开启，显著减少 OCR 次数。
# fallback：fast 模式识别失败后才继续跑大区域兜底。V8.6 默认开启，用“先快后准”提高识别率；识别慢时可设为 0。
OCR_FAST_MODE = os.environ.get("OCR_FAST_MODE", "1") == "1"
OCR_FALLBACK_ENABLED = os.environ.get("OCR_FALLBACK_ENABLED", "1") == "1"
OCR_EARLY_STOP = os.environ.get("OCR_EARLY_STOP", "1") == "1"
OCR_USE_ANGLE_CLS = os.environ.get("OCR_USE_ANGLE_CLS", "0") == "1"
OCR_CPU_THREADS = int(os.environ.get("OCR_CPU_THREADS", "4"))
OCR_DET_LIMIT_SIDE_LEN = int(os.environ.get("OCR_DET_LIMIT_SIDE_LEN", "960"))
OCR_MAX_ROI_IMAGES = int(os.environ.get("OCR_MAX_ROI_IMAGES", "5"))
# 没有“总里程/ODO”等标签时，低于该值的数字更可能是续航/本次行驶/电量，不自动当总里程。
OCR_MIN_AUTO_MILEAGE = int(os.environ.get("OCR_MIN_AUTO_MILEAGE", "1000"))


# =========================================================
# V8.1: 公网部署与短信验证码配置
# =========================================================
# SMS_PROVIDER 可选：console / aliyun
# - console：验证码写入控制台和 debug_ocr/sms_codes.txt，仅用于本地测试。
# - aliyun：使用阿里云短信服务发送真实短信，需要配置下方 ALIYUN_* 环境变量。
SMS_PROVIDER = os.environ.get("SMS_PROVIDER", "console").strip().lower()
SMS_CODE_TTL_SECONDS = int(os.environ.get("SMS_CODE_TTL_SECONDS", "300"))
SMS_SEND_COOLDOWN_SECONDS = int(os.environ.get("SMS_SEND_COOLDOWN_SECONDS", "60"))
SMS_MAX_ATTEMPTS = int(os.environ.get("SMS_MAX_ATTEMPTS", "5"))
SMS_CODE_LENGTH = int(os.environ.get("SMS_CODE_LENGTH", "6"))

# 阿里云短信。生产环境不要写死在代码里，请通过 .env 或服务器环境变量设置。
ALIYUN_ACCESS_KEY_ID = os.environ.get("ALIYUN_ACCESS_KEY_ID", "")
ALIYUN_ACCESS_KEY_SECRET = os.environ.get("ALIYUN_ACCESS_KEY_SECRET", "")
ALIYUN_SMS_REGION = os.environ.get("ALIYUN_SMS_REGION", "cn-hangzhou")
ALIYUN_SMS_SIGN_NAME = os.environ.get("ALIYUN_SMS_SIGN_NAME", "")
ALIYUN_SMS_TEMPLATE_CODE_LOGIN = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE_LOGIN", "")
ALIYUN_SMS_TEMPLATE_CODE_RESET = os.environ.get("ALIYUN_SMS_TEMPLATE_CODE_RESET", "")
ALIYUN_SMS_TEMPLATE_PARAM_NAME = os.environ.get("ALIYUN_SMS_TEMPLATE_PARAM_NAME", "code")

# Flask 生产部署配置
APP_HOST = os.environ.get("APP_HOST", "0.0.0.0")
APP_PORT = int(os.environ.get("APP_PORT", "5000"))
APP_DEBUG = os.environ.get("APP_DEBUG", "0") == "1"


# =========================================================
# V8.2: 数据保留与定期清理配置
# =========================================================
# DATA_RETENTION_MONTHS=0 表示不自动清理。
# 例如设置为 6，则自动清理 6 个月以前的行程记录。
DATA_RETENTION_MONTHS = int(os.environ.get("DATA_RETENTION_MONTHS", "0"))
DATA_CLEANUP_AUTO_ENABLED = os.environ.get("DATA_CLEANUP_AUTO_ENABLED", "0") == "1"
DATA_CLEANUP_CHECK_INTERVAL_SECONDS = int(os.environ.get("DATA_CLEANUP_CHECK_INTERVAL_SECONDS", "86400"))
DATA_CLEANUP_BACKUP_BEFORE_DELETE = os.environ.get("DATA_CLEANUP_BACKUP_BEFORE_DELETE", "1") == "1"
DATA_CLEANUP_DELETE_PHOTOS = os.environ.get("DATA_CLEANUP_DELETE_PHOTOS", "1") == "1"
