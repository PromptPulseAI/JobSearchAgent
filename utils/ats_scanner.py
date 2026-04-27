"""
ATS keyword extraction and coverage scoring — pure Python, zero AI tokens.
Extracts technical keywords from job descriptions and measures resume keyword coverage.
Separated into required vs. preferred tiers for accurate gap reporting.
"""
import re
from typing import Any, Dict, Set

# Hard-coded tech keyword patterns — add new patterns here as needed
_RAW_PATTERNS = [
    # Programming languages
    r"\b(?:Python|Java(?:Script)?|TypeScript|Go(?:lang)?|Rust|C\+\+|C#|Ruby|PHP|Swift|Kotlin|Scala|R|MATLAB|Perl|Elixir|Haskell)\b",
    # Cloud platforms
    r"\b(?:AWS|Azure|GCP|Google Cloud|Oracle Cloud|IBM Cloud|Alibaba Cloud)\b",
    # Infrastructure / DevOps
    r"\b(?:Docker|Kubernetes|K8s|Terraform|Ansible|Helm|Pulumi|Jenkins|CircleCI|GitHub Actions|GitLab CI|ArgoCD|Spinnaker)\b",
    # Databases
    r"\b(?:PostgreSQL|Postgres|MySQL|MariaDB|MongoDB|Redis|Elasticsearch|Cassandra|DynamoDB|BigQuery|Snowflake|Redshift|SQLite|Oracle|SQL Server|CockroachDB|ClickHouse)\b",
    # Frontend / Backend frameworks
    r"\b(?:React|Angular|Vue\.?js|Next\.?js|Nuxt|Svelte|Django|Flask|FastAPI|Spring(?:\s+Boot)?|Node\.?js|Express|Rails|Laravel|\.NET|ASP\.NET|Gin|Echo|Fiber)\b",
    # Patterns and methodologies
    r"\b(?:REST(?:ful)?|GraphQL|gRPC|WebSocket|microservices?|API|CI/CD|DevOps|SRE|TDD|BDD|Agile|Scrum|Kanban|SAFe|DDD|Event.driven)\b",
    # Data / ML / AI
    r"\b(?:Machine Learning|Deep Learning|NLP|LLM|PyTorch|TensorFlow|scikit-learn|Pandas|NumPy|Spark|Airflow|dbt|MLflow|Kafka|Flink|Databricks|Vertex AI|SageMaker)\b",
    # Security / Compliance
    r"\b(?:OAuth|SAML|JWT|HTTPS|SSL|TLS|SAST|DAST|SOC2|GDPR|PCI.?DSS|HIPAA|Zero.?Trust|IAM)\b",
    # Observability
    r"\b(?:Prometheus|Grafana|Datadog|New Relic|Splunk|ELK|OpenTelemetry|Jaeger|Dynatrace|PagerDuty)\b",
    # Version control / Collaboration
    r"\b(?:Git|GitHub|GitLab|Bitbucket|Jira|Confluence|Slack|Notion)\b",
]

_COMPILED = [re.compile(p, re.IGNORECASE) for p in _RAW_PATTERNS]

# Section markers that distinguish required from preferred
_REQUIRED_HEADER = re.compile(
    r"(?:requirements?|qualifications?|must.?have|required skills?|"
    r"you(?:'ll)?\s+(?:have|need|bring|must)|what\s+you(?:'ll)?\s+bring)"
    r"[\s:]*",
    re.IGNORECASE,
)
_PREFERRED_HEADER = re.compile(
    r"(?:preferred|nice.?to.?have|bonus|plus|advantage|good.?to.?have)"
    r"[\s:]*",
    re.IGNORECASE,
)
_SECTION_END = re.compile(
    r"(?:about\s+us|benefits?|compensation|what\s+we\s+offer|perks?|\Z)",
    re.IGNORECASE,
)


def _extract_from_text(text: str) -> Set[str]:
    found: Set[str] = set()
    for pattern in _COMPILED:
        found.update(m.lower() for m in pattern.findall(text))
    return found


def _split_sections(job_description: str) -> Dict[str, str]:
    """Split JD into required, preferred, and other text blocks."""
    req_match = _REQUIRED_HEADER.search(job_description)
    pref_match = _PREFERRED_HEADER.search(job_description)
    end_match = _SECTION_END.search(job_description)

    end_pos = end_match.start() if end_match else len(job_description)

    required_text = ""
    preferred_text = ""
    other_text = job_description

    if req_match:
        req_start = req_match.end()
        req_end = pref_match.start() if (pref_match and pref_match.start() > req_start) else end_pos
        required_text = job_description[req_start:req_end]

    if pref_match:
        pref_start = pref_match.end()
        preferred_text = job_description[pref_start:end_pos]

    return {"required": required_text, "preferred": preferred_text, "other": other_text}


def extract_keywords(job_description: str) -> Dict[str, Set[str]]:
    """
    Extract tech keywords from a job description, split by required vs. preferred.
    Returns {"required": set, "preferred": set, "all": set}.
    Keywords found in required section are NOT duplicated in preferred.
    """
    if not job_description:
        return {"required": set(), "preferred": set(), "all": set()}

    sections = _split_sections(job_description)

    required = _extract_from_text(sections["required"] or sections["other"])
    preferred_raw = _extract_from_text(sections["preferred"])
    preferred = preferred_raw - required  # No overlap

    return {"required": required, "preferred": preferred, "all": required | preferred}


def compute_coverage(resume_text: str, keywords: Dict[str, Set[str]]) -> Dict[str, Any]:
    """
    Compute ATS keyword coverage of a resume against extracted job keywords.
    Coverage % is based on required keywords only (the ATS gatekeeper).
    """
    if not resume_text:
        return _empty_coverage(keywords)

    text_lower = resume_text.lower()

    def _score(kw_set: Set[str]) -> tuple:
        matched = {kw for kw in kw_set if kw in text_lower}
        missing = kw_set - matched
        return sorted(matched), sorted(missing)

    req_matched, req_missing = _score(keywords["required"])
    pref_matched, pref_missing = _score(keywords["preferred"])
    all_matched, all_missing = _score(keywords["all"])

    total_required = len(keywords["required"])
    coverage_pct = round(len(req_matched) / total_required * 100, 1) if total_required else 100.0

    return {
        "coverage_percent": coverage_pct,
        "required": {
            "matched": req_matched,
            "missing": req_missing,
            "total": total_required,
            "matched_count": len(req_matched),
        },
        "preferred": {
            "matched": pref_matched,
            "missing": pref_missing,
            "total": len(keywords["preferred"]),
            "matched_count": len(pref_matched),
        },
        "overall": {
            "matched": all_matched,
            "missing": all_missing,
            "total": len(keywords["all"]),
            "coverage_percent": round(len(all_matched) / max(len(keywords["all"]), 1) * 100, 1),
        },
    }


def _empty_coverage(keywords: Dict[str, Set[str]]) -> Dict[str, Any]:
    return {
        "coverage_percent": 0.0,
        "required": {"matched": [], "missing": sorted(keywords["required"]), "total": len(keywords["required"]), "matched_count": 0},
        "preferred": {"matched": [], "missing": sorted(keywords["preferred"]), "total": len(keywords["preferred"]), "matched_count": 0},
        "overall": {"matched": [], "missing": sorted(keywords["all"]), "total": len(keywords["all"]), "coverage_percent": 0.0},
    }
