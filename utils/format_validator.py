"""
Resume and cover letter format validation — pure Python, zero AI tokens.
Checks: section headers, length, bullet consistency, and optional spell check.
Results are structured dicts so the Reviewer can include them in fix_instructions.json.
"""
import re
from typing import Any, Dict, List

# pyspellchecker is optional — gracefully degrade if not installed
try:
    from spellchecker import SpellChecker as _SpellChecker
    _spell = _SpellChecker()
    SPELL_CHECK_AVAILABLE = True
except ImportError:
    _spell = None
    SPELL_CHECK_AVAILABLE = False

# Common tech terms that pyspellchecker incorrectly flags as misspelled
_TECH_ALLOWLIST = {
    # Languages & runtimes
    "golang", "kotlin", "typescript", "javascript", "nodejs",
    "pytorch", "tensorflow", "numpy", "pandas", "pytest",
    "fastapi", "celery", "gunicorn", "uvicorn", "django", "flask",
    "sqlalchemy", "alembic", "pydantic", "asyncio",
    # Cloud & infrastructure
    "kubernetes", "kubectl", "helm", "istio", "envoy", "nginx",
    "terraform", "ansible", "pulumi", "serverless",
    "aws", "gcp", "azure", "vpc", "iam", "eks", "gke", "aks",
    "fargate", "lambda", "s3", "rds", "sns", "sqs", "ecr", "ecs",
    # Databases & data
    "postgresql", "mysql", "mongodb", "elasticsearch", "opensearch",
    "redis", "cassandra", "dynamodb", "cockroachdb", "clickhouse",
    "snowflake", "bigquery", "databricks", "airflow", "dbt",
    "kafka", "kinesis", "flink", "spark",
    # Observability & DevOps
    "datadog", "grafana", "prometheus", "splunk", "opentelemetry",
    "pagerduty", "sentry", "jaeger", "zipkin", "dockerfile",
    "cicd", "jenkins", "argocd", "spinnaker",
    # Patterns & concepts
    "microservices", "monorepo", "devops", "devsecops", "gitops",
    "codebase", "repo", "repos", "refactoring", "refactor",
    "observability", "idempotent", "idempotency", "pagination",
    "websockets", "webhooks", "middleware",
    "api", "apis", "sdk", "sdks", "cli", "sso", "mfa", "rbac",
    # Security & auth
    "oauth", "saml", "jwt", "tls", "ssl", "mtls", "oidc", "ldap",
    "cryptography", "bcrypt",
    # SaaS / domain terms
    "saas", "paas", "iaas", "fintech", "healthtech", "edtech",
    "multitenancy", "multitenant", "autoscaling", "sidecar",
    "loadbalancer", "failover", "backoff", "throughput", "latency",
    # ML / AI
    "mlops", "mlflow", "kubeflow", "sagemaker", "automl",
    "embeddings", "tokenizer", "tokenization", "llm", "llms", "rag",
    "finetuning", "finetuned", "pretrained",
    # Tooling often flagged
    "linting", "linted", "eslint", "pylint", "mypy", "flake",
    "prettier", "changelog", "semver", "mocking",
    "serialization", "deserialization", "serialize", "deserialize",
    "parameterized", "parametrize",
    # Graphql / grpc / misc protocols
    "graphql", "grpc", "protobuf", "thrift", "avro",
}

# Resume section groups: at least one from each group must appear
_REQUIRED_SECTION_GROUPS = [
    {"experience", "work experience", "professional experience", "employment history", "employment"},
    {"education", "academic background", "academics"},
    {"skills", "technical skills", "core competencies", "competencies", "expertise"},
    {"summary", "profile", "objective", "professional summary", "about"},
]

_SECTION_HEADER_RE = re.compile(r"^[ \t]*([A-Z][A-Za-z\s&/\-]{2,40}):?[ \t]*$", re.MULTILINE)
_BULLET_RE = re.compile(r"^[ \t]*[-•▪◦◾►*][ \t]", re.MULTILINE)


def validate_resume(text: str, page_count: int = 1) -> Dict[str, Any]:
    """
    Validate a resume's format.
    Returns {"passed": bool, "error_count": int, "warning_count": int, "issues": [...], ...}
    """
    issues: List[Dict[str, str]] = []
    headers_found = {h.strip().lower() for h in _SECTION_HEADER_RE.findall(text)}

    # 1. Required section presence
    for group in _REQUIRED_SECTION_GROUPS:
        if not headers_found.intersection(group):
            issues.append({
                "type": "missing_section",
                "severity": "error",
                "detail": f"Missing required section. Expected one of: {', '.join(sorted(group))}",
            })

    # 2. Length
    word_count = len(text.split())
    if word_count < 200:
        issues.append({
            "type": "too_short",
            "severity": "warning",
            "detail": f"Resume appears very short ({word_count} words). Expected 400+.",
        })
    if page_count > 2:
        issues.append({
            "type": "too_long",
            "severity": "warning",
            "detail": f"Resume is {page_count} pages; ATS prefers 1-2 pages.",
        })

    # 3. Bullet consistency
    bullets = _BULLET_RE.findall(text)
    unique_styles = {b.strip() for b in bullets}
    if len(unique_styles) > 2:
        issues.append({
            "type": "inconsistent_bullets",
            "severity": "warning",
            "detail": f"Multiple bullet styles found: {unique_styles}. Use a single consistent style.",
        })

    # 4. Spell check (optional — only on lowercase words to skip proper nouns + tech terms)
    spell_errors: List[str] = []
    if SPELL_CHECK_AVAILABLE and _spell is not None:
        words = re.findall(r"\b[a-z]{4,}\b", text)
        words_to_check = [w for w in words if w not in _TECH_ALLOWLIST]
        misspelled = _spell.unknown(words_to_check)
        spell_errors = sorted(misspelled)[:10]  # Cap at 10 to avoid noise
        if spell_errors:
            issues.append({
                "type": "spelling",
                "severity": "warning",
                "detail": f"Possible misspellings (check manually): {', '.join(spell_errors)}",
            })

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    return {
        "passed": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
        "word_count": word_count,
        "page_count": page_count,
        "spell_check_available": SPELL_CHECK_AVAILABLE,
        "spell_errors": spell_errors,
    }


def validate_cover_letter(text: str) -> Dict[str, Any]:
    """
    Validate a cover letter's format.
    Returns {"passed": bool, "error_count": int, "warning_count": int, "issues": [...], ...}
    """
    issues: List[Dict[str, str]] = []
    word_count = len(text.split())

    if word_count < 100:
        issues.append({
            "type": "too_short",
            "severity": "error",
            "detail": f"Cover letter is too short ({word_count} words; minimum ~200).",
        })
    if word_count > 600:
        issues.append({
            "type": "too_long",
            "severity": "warning",
            "detail": f"Cover letter is too long ({word_count} words; target under 400).",
        })

    # Generic openers are red flags for ATS and human reviewers
    text_lower = text.lower()
    bad_openers = [
        "i am writing to express my interest",
        "i am writing to apply",
        "to whom it may concern",
    ]
    for opener in bad_openers:
        if opener in text_lower:
            issues.append({
                "type": "generic_opener",
                "severity": "warning",
                "detail": f"Generic opener detected: '{opener}'. Lead with impact instead.",
            })

    errors = [i for i in issues if i["severity"] == "error"]
    warnings = [i for i in issues if i["severity"] == "warning"]

    return {
        "passed": len(errors) == 0,
        "error_count": len(errors),
        "warning_count": len(warnings),
        "issues": issues,
        "word_count": word_count,
    }
