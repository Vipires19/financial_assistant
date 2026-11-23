from tests.helpers import create_category, default_account, headers, post_entry, register
from app.db.time import local_today


def test_category_can_be_renamed_archived_and_restored(client):
    _, csrf = register(client)
    created = create_category(client, csrf, "Mercado")
    renamed = client.patch(
        f"/categories/{created['id']}",
        json={"name": "Feira"},
        headers=headers(csrf),
    )
    assert renamed.status_code == 200
    assert renamed.json()["name"] == "Feira"
    duplicate = create_category_raw(client, csrf, "feira")
    assert duplicate.status_code == 409
    archived = client.post(f"/categories/{created['id']}/archive", headers=headers(csrf))
    assert archived.status_code == 200
    assert client.get("/categories").json() == [
        item for item in client.get("/categories?include_archived=true").json() if not item["archived_at"] or item["is_internal"]
    ]
    visible = client.get("/categories").json()
    assert all(item["id"] != created["id"] for item in visible)
    historical = client.get("/categories?include_archived=true").json()
    assert any(item["id"] == created["id"] for item in historical)
    account = default_account(client)
    rejected = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": created["id"],
            "kind": "expense",
            "amount": "5.00",
            "occurred_on": local_today().isoformat(),
        },
        headers=headers(csrf),
    )
    assert rejected.status_code == 422
    restored = client.post(f"/categories/{created['id']}/reactivate", headers=headers(csrf))
    assert restored.status_code == 200
    assert restored.json()["archived_at"] is None


def create_category_raw(client, csrf, name):
    return client.post("/categories", json={"name": name}, headers=headers(csrf))


def test_internal_category_cannot_be_archived_or_used_as_expense(client):
    _, csrf = register(client)
    internal = next(item for item in client.get("/categories").json() if item["is_internal"])
    archived = client.post(f"/categories/{internal['id']}/archive", headers=headers(csrf))
    assert archived.status_code == 422
    account = default_account(client)
    rejected = client.post(
        "/transactions",
        json={
            "account_id": account["id"],
            "category_id": internal["id"],
            "kind": "expense",
            "amount": "5.00",
            "occurred_on": local_today().isoformat(),
        },
        headers=headers(csrf),
    )
    assert rejected.status_code == 422
    grouped = client.post(
        "/categories",
        json={"name": "Lazer", "group_code": "lazer"},
        headers=headers(csrf),
    )
    assert grouped.status_code == 422


def test_archived_category_remains_on_existing_entry_and_can_replace_another(client):
    _, csrf = register(client)
    account = default_account(client)
    first = create_category(client, csrf, "Mercado")
    second = create_category(client, csrf, "Farmácia")
    entry = post_entry(
        client,
        csrf,
        account["id"],
        first["id"],
        "expense",
        "8.00",
        local_today().isoformat(),
    )
    assert client.post(f"/categories/{second['id']}/archive", headers=headers(csrf)).status_code == 200
    edited = client.patch(
        f"/transactions/{entry['id']}",
        json={"category_id": second["id"]},
        headers=headers(csrf),
    )
    assert edited.status_code == 200, edited.text
    assert edited.json()["category_name"] == "Farmácia"
