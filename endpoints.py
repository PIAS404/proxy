# endpoints.py
# এখানে provider এর real endpoints বসাতে হবে (docs / network tab থেকে)
# Paths can be full URL or relative.

ENDPOINTS = {
    # --- “Account/Status” ---
    "status": {"method": "GET", "path": "/api/status"},  # verify key works

    # --- “Proxy” ---
    "proxy_list": {"method": "GET", "path": "/api/proxy/list"},
    "proxy_rotate": {"method": "POST", "path": "/api/proxy/rotate"},  # maybe requires id/session

    # --- “Traffic / Stats” ---
    "traffic": {"method": "GET", "path": "/api/traffic"},

    # --- “Whitelist” ---
    "whitelist_list": {"method": "GET", "path": "/api/whitelist/list"},
    "whitelist_add": {"method": "POST", "path": "/api/whitelist/add"},
    "whitelist_remove": {"method": "POST", "path": "/api/whitelist/remove"},

    # --- “Sub-Accounts (if available)” ---
    "subusers": {"method": "GET", "path": "/api/subuser/list"},
    "subuser_create": {"method": "POST", "path": "/api/subuser/create"},
    "subuser_disable": {"method": "POST", "path": "/api/subuser/disable"},
}
