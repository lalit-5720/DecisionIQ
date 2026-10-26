"""Single source of truth for who may do what. The UI reads the same data from /api/auth/me."""

CAPABILITIES = {
    "view": "View forecasts & executive dashboards",
    "approve_actions": "Approve prescriptive POs, price markdowns & alert decisions",
    "upload_data": "Upload raw POS & ingestion files",
    "run_analysis": "Trigger model retraining, risk scans & feature engineering",
    "modify_thresholds": "Modify anomaly sensitivity & risk thresholds",
    "manage_users": "Manage users, SSO & store assignments",
    "view_audit": "View the system audit trail",
}

ROLE_CAPS = {
    "Admin": set(CAPABILITIES),
    "Manager": {"view", "approve_actions", "upload_data", "run_analysis", "view_audit"},
    "Analyst": {"view", "upload_data"},
}
ROLES = list(ROLE_CAPS)

# Which capability guards each settings section
SETTINGS_SECTION_CAP = {"risk": "modify_thresholds", "compliance": "modify_thresholds", "inventory": "approve_actions",
                        "retraining": "run_analysis", "reports": "approve_actions"}


def can(role: str, capability: str) -> bool:
    return capability in ROLE_CAPS.get(role, set())


def matrix() -> list[dict]:
    """Rows for the settings page. 'locked' = a capability a Manager might expect but is deliberately kept admin-only."""
    rows = []
    for key, label in CAPABILITIES.items():
        row = {"key": key, "capability": label}
        for role in ROLES:
            allowed = key in ROLE_CAPS[role]
            row[role.lower()] = True if allowed else ("locked" if role == "Manager" and key in ("modify_thresholds", "manage_users") else False)
        rows.append(row)
    return rows
