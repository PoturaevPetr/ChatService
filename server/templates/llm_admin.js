(function () {
  const secretInput = document.getElementById("admin-secret");
  const searchInput = document.getElementById("search-q");
  const reloadBtn = document.getElementById("reload-btn");
  const statusEl = document.getElementById("status");
  const toastEl = document.getElementById("toast");
  const tbody = document.getElementById("users-body");

  const modal = document.getElementById("user-modal");
  const modalBackdrop = document.getElementById("user-modal-backdrop");
  const modalClose = document.getElementById("user-modal-close");
  const modalCancel = document.getElementById("user-modal-cancel");
  const modalSave = document.getElementById("user-modal-save");
  const modalTitle = document.getElementById("user-modal-title");
  const modalSubtitle = document.getElementById("user-modal-subtitle");
  const modalFields = document.getElementById("user-modal-fields");
  const modalLlmCheckbox = document.getElementById("user-modal-llm-checkbox");
  const modalSaveStatus = document.getElementById("user-modal-save-status");

  const SECRET_STORAGE_KEY = "kindred_llm_admin_secret";
  let selectedUser = null;
  let saving = false;

  function esc(s) {
    return String(s ?? "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function displayName(row) {
    const parts = [row.last_name, row.first_name, row.middle_name].filter(Boolean);
    if (parts.length) return parts.join(" ");
    return row.username;
  }

  function formatDate(value) {
    if (!value) return "—";
    try {
      return new Date(value).toLocaleString("ru-RU");
    } catch {
      return String(value);
    }
  }

  function boolLabel(value) {
    return value ? "да" : "нет";
  }

  function adminSecret() {
    return (secretInput?.value || "").trim();
  }

  function showToast(message, kind) {
    if (!toastEl) return;
    toastEl.textContent = message;
    toastEl.classList.remove("hidden", "border-emerald-500/30", "bg-emerald-500/10", "text-emerald-200");
    toastEl.classList.remove("border-rose-500/30", "bg-rose-500/10", "text-rose-200");
    if (kind === "error") {
      toastEl.classList.add("border-rose-500/30", "bg-rose-500/10", "text-rose-200");
    } else {
      toastEl.classList.add("border-emerald-500/30", "bg-emerald-500/10", "text-emerald-200");
    }
    window.setTimeout(() => toastEl.classList.add("hidden"), 4000);
  }

  function setModalSaveStatus(message, kind) {
    if (!modalSaveStatus) return;
    if (!message) {
      modalSaveStatus.classList.add("hidden");
      modalSaveStatus.textContent = "";
      return;
    }
    modalSaveStatus.textContent = message;
    modalSaveStatus.classList.remove("hidden", "text-emerald-300", "text-rose-300");
    modalSaveStatus.classList.add(kind === "error" ? "text-rose-300" : "text-emerald-300");
  }

  function renderField(label, value) {
    return `
      <div class="rounded-xl border border-slate-800 bg-slate-950/40 px-3 py-2.5">
        <dt class="text-[11px] font-medium uppercase tracking-wide text-slate-500">${esc(label)}</dt>
        <dd class="mt-1 break-all text-sm text-slate-100">${esc(value)}</dd>
      </div>`;
  }

  function openModal(user) {
    selectedUser = user;
    if (!modal) return;

    modalTitle.textContent = displayName(user);
    modalSubtitle.textContent = `${user.username} · ${user.id}`;
    modalLlmCheckbox.checked = !!user.llm_enabled;
    setModalSaveStatus("", "ok");

    modalFields.innerHTML = [
      renderField("Username", user.username),
      renderField("ID", user.id),
      renderField("Service ID", user.service_id),
      renderField("Имя", user.first_name || "—"),
      renderField("Фамилия", user.last_name || "—"),
      renderField("Отчество", user.middle_name || "—"),
      renderField("Дата рождения", user.birth_date || "—"),
      renderField("Активен", boolLabel(user.is_active)),
      renderField("Подтверждён", boolLabel(user.is_verified)),
      renderField("Аватар", user.has_avatar ? "есть" : "нет"),
      renderField("Создан", formatDate(user.created_at)),
      renderField("Последний вход", formatDate(user.last_login)),
      renderField("Был в сети", formatDate(user.last_seen_at)),
    ].join("");

    modal.classList.remove("hidden");
    modal.setAttribute("aria-hidden", "false");
    document.body.classList.add("overflow-hidden");
  }

  function closeModal() {
    if (!modal) return;
    modal.classList.add("hidden");
    modal.setAttribute("aria-hidden", "true");
    document.body.classList.remove("overflow-hidden");
    selectedUser = null;
    setModalSaveStatus("", "ok");
  }

  async function fetchUserDetail(userId) {
    const secret = adminSecret();
    if (!secret) throw new Error("Укажите admin secret.");
    const url = `/api/v1/llm/admin/users/${encodeURIComponent(userId)}?admin_secret=${encodeURIComponent(secret)}`;
    const res = await fetch(url, { headers: { Accept: "application/json" } });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    return data;
  }

  async function loadUsers() {
    const secret = adminSecret();
    if (!secret) {
      statusEl.textContent = "Укажите admin secret.";
      return;
    }
    try {
      sessionStorage.setItem(SECRET_STORAGE_KEY, secret);
    } catch {
      /* ignore */
    }

    statusEl.textContent = "Загрузка…";
    tbody.innerHTML = "";
    const q = encodeURIComponent((searchInput?.value || "").trim());
    const url = `/api/v1/llm/admin/users?admin_secret=${encodeURIComponent(secret)}&q=${q}`;
    try {
      const res = await fetch(url, { headers: { Accept: "application/json" } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        statusEl.textContent = data.detail || `Ошибка HTTP ${res.status}`;
        return;
      }
      const items = Array.isArray(data.items) ? data.items : [];
      statusEl.textContent = items.length
        ? `Найдено: ${items.length}. Нажмите на строку, чтобы открыть карточку.`
        : "Пользователи не найдены.";

      tbody.innerHTML = items
        .map((row) => {
          const enabled = !!row.llm_enabled;
          const badge = enabled
            ? '<span class="rounded-full bg-emerald-500/15 px-2 py-0.5 text-xs text-emerald-300">on</span>'
            : '<span class="rounded-full bg-slate-700 px-2 py-0.5 text-xs text-slate-300">off</span>';
          return `
            <tr
              class="cursor-pointer transition hover:bg-slate-900/70"
              data-user-id="${esc(row.id)}"
              tabindex="0"
              role="button"
              aria-label="Открыть ${esc(displayName(row))}"
            >
              <td class="px-4 py-3">
                <div class="font-medium text-slate-100">${esc(displayName(row))}</div>
                <div class="text-xs text-slate-500">${esc(row.username)}</div>
              </td>
              <td class="px-4 py-3 text-slate-300">${esc(row.service_id)}</td>
              <td class="px-4 py-3">${row.is_active ? "да" : "нет"}</td>
              <td class="px-4 py-3">${badge}</td>
            </tr>`;
        })
        .join("");

      tbody.querySelectorAll("tr[data-user-id]").forEach((row) => {
        row.addEventListener("click", () => {
          void openUserModal(row.getAttribute("data-user-id"));
        });
        row.addEventListener("keydown", (event) => {
          if (event.key === "Enter" || event.key === " ") {
            event.preventDefault();
            void openUserModal(row.getAttribute("data-user-id"));
          }
        });
      });
    } catch (e) {
      statusEl.textContent = e instanceof Error ? e.message : "Ошибка сети";
    }
  }

  async function openUserModal(userId) {
    if (!userId) return;
    try {
      statusEl.textContent = "Загрузка карточки пользователя…";
      const user = await fetchUserDetail(userId);
      openModal(user);
      statusEl.textContent = "Карточка пользователя открыта.";
    } catch (e) {
      showToast(e instanceof Error ? e.message : "Не удалось загрузить пользователя", "error");
      statusEl.textContent = "Ошибка загрузки карточки пользователя.";
    }
  }

  async function saveModalAccess() {
    if (!selectedUser || saving) return;
    const secret = adminSecret();
    if (!secret) {
      setModalSaveStatus("Укажите admin secret.", "error");
      return;
    }

    saving = true;
    modalSave.disabled = true;
    setModalSaveStatus("Сохранение…", "ok");

    try {
      const res = await fetch(`/api/v1/llm/admin/users/${encodeURIComponent(selectedUser.id)}/access`, {
        method: "PATCH",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          admin_secret: secret,
          llm_enabled: !!modalLlmCheckbox.checked,
        }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        throw new Error(data.detail || `HTTP ${res.status}`);
      }

      selectedUser = data;
      openModal(data);
      setModalSaveStatus(
        data.llm_enabled ? "Доступ к LLM включён." : "Доступ к LLM выключен.",
        "ok",
      );
      showToast(`Сохранено для ${data.username}`, "ok");
      void loadUsers();
    } catch (e) {
      setModalSaveStatus(e instanceof Error ? e.message : "Ошибка сохранения", "error");
    } finally {
      saving = false;
      modalSave.disabled = false;
    }
  }

  reloadBtn?.addEventListener("click", () => void loadUsers());
  searchInput?.addEventListener("keydown", (e) => {
    if (e.key === "Enter") void loadUsers();
  });
  modalClose?.addEventListener("click", closeModal);
  modalCancel?.addEventListener("click", closeModal);
  modalBackdrop?.addEventListener("click", closeModal);
  modalSave?.addEventListener("click", () => void saveModalAccess());
  window.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && modal && !modal.classList.contains("hidden")) {
      closeModal();
    }
  });

  try {
    const savedSecret = sessionStorage.getItem(SECRET_STORAGE_KEY);
    if (savedSecret && secretInput) secretInput.value = savedSecret;
  } catch {
    /* ignore */
  }
})();
