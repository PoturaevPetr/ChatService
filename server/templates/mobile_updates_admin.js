(function () {
  const form = document.getElementById("release-upload-form");
  const errorBox = document.getElementById("form-error");
  const successBox = document.getElementById("form-success");
  const submitBtn = document.getElementById("release-upload-submit");
  const tableBody = document.getElementById("releases-table-body");
  const releasesCount = document.getElementById("releases-count");
  if (!form || !errorBox || !tableBody || !releasesCount) return;

  const allowedByPlatform = {
    android: [".apk", ".aab"],
    ios: [".ipa"],
    macos: [".dmg", ".pkg", ".app.zip"],
    windows: [".exe", ".msi", ".msix"],
  };

  function showError(msg) {
    if (successBox) {
      successBox.textContent = "";
      successBox.classList.add("hidden");
    }
    errorBox.textContent = msg;
    errorBox.classList.remove("hidden");
  }

  function clearError() {
    errorBox.textContent = "";
    errorBox.classList.add("hidden");
  }

  function showSuccess(msg) {
    if (!successBox) return;
    clearError();
    successBox.textContent = msg;
    successBox.classList.remove("hidden");
  }

  function fileExtension(name) {
    const lower = (name || "").toLowerCase();
    if (lower.endsWith(".app.zip")) return ".app.zip";
    const idx = lower.lastIndexOf(".");
    return idx >= 0 ? lower.slice(idx) : "";
  }

  function validate() {
    clearError();

    const platform = (form.elements.platform?.value || "").trim().toLowerCase();
    const version = (form.elements.version?.value || "").trim();
    const description = (form.elements.description?.value || "").trim();
    const minSupported = (form.elements.min_supported_version?.value || "").trim();
    const forceType = (form.elements.force_update?.value || "").trim().toLowerCase();
    const remind = Number(form.elements.remind_after_hours?.value || 0);
    const adminSecret = (form.elements.admin_secret?.value || "").trim();
    const fileInput = form.elements.release_file;
    const file = fileInput?.files?.[0];

    if (!platform || !version || !description || !minSupported || !forceType || !adminSecret) {
      showError("Все поля обязательны для заполнения.");
      return false;
    }
    if (!/^\d+\.\d+\.\d+$/.test(version)) {
      showError("Версия должна быть в формате X.Y.Z, например 0.5.0.");
      return false;
    }
    if (!/^\d+\.\d+\.\d+$/.test(minSupported)) {
      showError("Минимальная версия должна быть в формате X.Y.Z, например 0.4.0.");
      return false;
    }
    if (forceType !== "soft" && forceType !== "force") {
      showError("Тип обновления должен быть soft или force.");
      return false;
    }
    if (!Number.isFinite(remind) || remind < 1) {
      showError("Поле 'Повтор soft-уведомления' должно быть >= 1.");
      return false;
    }
    if (!file) {
      showError("Нужно выбрать файл обновления.");
      return false;
    }
    if (file.type && (file.type.startsWith("audio/") || file.type.startsWith("video/") || file.type.startsWith("image/"))) {
      showError("Нельзя загружать аудио, видео или изображения.");
      return false;
    }
    const ext = fileExtension(file.name);
    const allowed = allowedByPlatform[platform] || [];
    if (!allowed.includes(ext)) {
      showError(`Недопустимый формат для ${platform}. Разрешено: ${allowed.join(", ")}`);
      return false;
    }
    return true;
  }

  function escapeHtml(str) {
    return String(str)
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;")
      .replaceAll("'", "&#039;");
  }

  function formatCreatedAt(value) {
    if (!value) return "";
    const d = new Date(value);
    if (Number.isNaN(d.getTime())) return value;
    return d.toLocaleString("ru-RU");
  }

  function renderRows(items) {
    releasesCount.textContent = `${items.length} items`;
    if (!items.length) {
      tableBody.innerHTML =
        '<tr><td colspan="7" class="px-4 py-6 text-center text-slate-400">No releases yet</td></tr>';
      return;
    }
    tableBody.innerHTML = items
      .map((r) => {
        const latestBadge = r.is_latest
          ? '<span class="rounded-full border border-emerald-400/30 bg-emerald-500/10 px-2 py-0.5 text-xs font-medium text-emerald-300">latest</span>'
          : "";
        const forceBadge = r.force_update
          ? '<span class="rounded-full border border-amber-400/30 bg-amber-500/10 px-2 py-0.5 text-xs font-medium text-amber-300">yes</span>'
          : '<span class="rounded-full border border-slate-600 bg-slate-700/40 px-2 py-0.5 text-xs font-medium text-slate-300">no</span>';
        return `
          <tr class="text-slate-200">
            <td class="px-4 py-3">${escapeHtml(formatCreatedAt(r.created_at))}</td>
            <td class="px-4 py-3">${escapeHtml(r.platform || "")}</td>
            <td class="px-4 py-3">
              <div class="flex items-center gap-2">
                <span>${escapeHtml(r.version || "")}</span>
                ${latestBadge}
              </div>
            </td>
            <td class="px-4 py-3">${forceBadge}</td>
            <td class="px-4 py-3">${escapeHtml(r.min_supported_version || "")}</td>
            <td class="px-4 py-3">${escapeHtml(String(r.size_bytes ?? ""))}</td>
            <td class="px-4 py-3">
              <a href="${escapeHtml(r.download_url || "#")}" class="inline-flex items-center rounded-lg border border-indigo-400/30 bg-indigo-500/10 px-2.5 py-1 text-xs font-medium text-indigo-200 transition hover:bg-indigo-500/20">download</a>
            </td>
          </tr>
        `;
      })
      .join("");
  }

  async function fetchReleases() {
    const res = await fetch("/api/v1/mobile/admin/releases/list", {
      headers: { Accept: "application/json" },
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      throw new Error(data.detail || `HTTP ${res.status}`);
    }
    renderRows(Array.isArray(data.items) ? data.items : []);
  }

  form.addEventListener("submit", function (e) {
    e.preventDefault();
    if (!validate()) return;
    const body = new FormData(form);
    if (submitBtn) {
      submitBtn.disabled = true;
      submitBtn.textContent = "Загрузка...";
    }
    fetch("/api/v1/mobile/admin/releases/upload", {
      method: "POST",
      body,
      headers: {
        Accept: "application/json",
        "X-Requested-With": "XMLHttpRequest",
      },
    })
      .then(async (res) => {
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          throw new Error(data.detail || `HTTP ${res.status}`);
        }
        showSuccess(data.message || "Release uploaded");
        form.reset();
        const remindInput = form.elements.remind_after_hours;
        if (remindInput && !remindInput.value) {
          remindInput.value = "24";
        }
        await fetchReleases();
      })
      .catch((err) => {
        showError(err instanceof Error ? err.message : "Ошибка загрузки");
      })
      .finally(() => {
        if (submitBtn) {
          submitBtn.disabled = false;
          submitBtn.textContent = "Загрузить релиз";
        }
      });
  });

  fetchReleases().catch((err) => {
    showError(err instanceof Error ? err.message : "Не удалось загрузить список релизов");
  });
})();

