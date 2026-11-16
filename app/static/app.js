"use strict";

(() => {
  const $ = (selector, parent = document) => parent.querySelector(selector);
  const $$ = (selector, parent = document) => [...parent.querySelectorAll(selector)];
  const escape = (value) => String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
  const number = (value, digits = 2) => new Intl.NumberFormat("ru-RU", {
    maximumFractionDigits: digits,
  }).format(value);
  const categories = {
    classical_ml: "Классическое ML", deep_learning: "Глубокое обучение", hybrid: "Гибридный",
  };
  const signals = { eeg: "EEG", ecg: "ECG", eog: "EOG", imu: "IMU", video_features: "Видео" };
  const events = { view: "Просмотр", save: "Сохранение", select: "Выбор", rating: "Оценка" };
  const eventIcons = { view: "↗", save: "+", select: "✓", rating: "★" };
  const dateFormat = new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" });
  const state = {
    token: "", user: null, authEpoch: 0, page: "catalog", catalog: [], catalogCursor: null,
    catalogQuery: "", catalogRequest: 0, catalogBusy: false, history: [], historyCursor: null,
    historyRequest: 0, recommendationsRequest: 0, analyticsRequest: 0, detailRequest: 0,
    detail: null, editing: null, authMode: "login", afterAuth: null, pendingEvents: new Map(),
  };
  try { state.token = sessionStorage.getItem("edge-catalog-token") || ""; } catch { /* Memory-only session. */ }

  function toast(message, error = false) {
    const element = document.createElement("div");
    element.className = `toast${error ? " error" : ""}`;
    element.innerHTML = `<span class="red-dot"></span><span>${escape(message)}</span>`;
    $("#toasts").append(element);
    setTimeout(() => element.remove(), 5500);
  }

  function storeToken(token) {
    state.token = token;
    try {
      if (token) sessionStorage.setItem("edge-catalog-token", token);
      else sessionStorage.removeItem("edge-catalog-token");
    } catch { /* The current session still works when browser storage is disabled. */ }
  }

  function forgetSession() {
    state.authEpoch += 1;
    storeToken("");
    state.user = null;
    state.pendingEvents.clear();
    state.history = [];
    $("#history-list").replaceChildren();
    $("#history-more").hidden = true;
    $("#analytics-content").replaceChildren();
    $("#recommendations-grid").replaceChildren();
    $("#device-summary").replaceChildren();
    renderAccount();
  }

  function errorMessage(status, detail) {
    const known = {
      "Email already registered": "Этот email уже зарегистрирован. Попробуйте войти.",
      "Email already exists": "Этот email уже зарегистрирован. Попробуйте войти.",
      "This slug and version already exist": "Модель с таким slug и версией уже существует.",
      "Model not found": "Модель не найдена или уже архивирована.",
      "Active model not found": "Эта модель уже архивирована.",
      "Database operation unavailable": "База данных временно недоступна. Повторите позже.",
    };
    if (typeof detail === "string" && known[detail]) return known[detail];
    if (status === 401) return "Не удалось войти или срок сеанса истёк. Проверьте email и пароль.";
    if (status === 403) return "Это действие доступно только администратору.";
    if (status === 409) return "Такая запись уже существует. Проверьте введённые данные.";
    if (status === 422) {
      const labels = {
        email: "Email", password: "Пароль", display_name: "Ваше имя", name: "Название",
        slug: "Slug", version: "Версия", description: "Описание", category: "Метод",
        signal: "Тип сигнала", signals: "Сигналы", tags: "Теги (до 15 тегов, до 40 символов каждый)",
        memory_budget_mb: "Бюджет памяти", memory_mb: "Память", max_memory_mb: "Память, до",
        latency_ms: "Задержка", max_latency_ms: "Максимальная задержка",
        reference_device: "Эталонное устройство", f1: "F1", dataset: "Датасет",
        protocol: "Протокол оценки", q: "Поиск",
      };
      const fields = Array.isArray(detail) ? [...new Set(detail.map((d) => labels[d.loc?.at(-1)]).filter(Boolean))] : [];
      return `Проверьте заполнение полей${fields.length ? `: ${fields.join(", ")}` : ""}.`;
    }
    if (status === 404) return "Запись не найдена или уже архивирована.";
    if (status >= 500) return "Сервер временно недоступен. Попробуйте ещё раз.";
    return "Не удалось выполнить действие. Проверьте данные и повторите.";
  }

  async function api(path, { method = "GET", body, form = false, auth = true } = {}) {
    const token = auth ? state.token : "";
    const headers = { Accept: "application/json" };
    if (token) headers.Authorization = `Bearer ${token}`;
    if (body !== undefined) headers["Content-Type"] = form ? "application/x-www-form-urlencoded" : "application/json";
    let response;
    try {
      response = await fetch(path, {
        method, headers, body: body === undefined ? undefined : form ? new URLSearchParams(body) : JSON.stringify(body),
        signal: AbortSignal.timeout(20000),
      });
    } catch {
      throw new Error("Нет связи с сервером. Проверьте, что проект и MongoDB запущены.");
    }
    const result = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      if (response.status === 401 && token && token === state.token) {
        forgetSession();
        $$("dialog[open]").forEach((dialog) => dialog.close());
        if (state.page !== "catalog") renderPage(state.page);
      }
      const error = new Error(errorMessage(response.status, result?.detail));
      error.status = response.status;
      throw error;
    }
    return result;
  }

  const loading = () => '<div class="loading-state" role="status">Загружаем данные…</div>';
  function empty(title, message, action = "", label = "") {
    return `<div class="empty-state"><h3>${escape(title)}</h3><p>${escape(message)}</p>${action ? `<button class="button button-dark" data-action="${escape(action)}">${escape(label)} ↗</button>` : ""}</div>`;
  }
  function showError(selector, error, retryAction) {
    $(selector).innerHTML = empty("Не удалось загрузить", error.message, retryAction, "Попробовать ещё раз");
  }
  function setFormError(id, message = "") {
    const element = $(id);
    element.textContent = message;
    element.hidden = !message;
  }
  async function busy(button, operation) {
    if (button.disabled) return;
    button.disabled = true;
    button.setAttribute("aria-busy", "true");
    try { await operation(); }
    finally { button.disabled = false; button.removeAttribute("aria-busy"); }
  }

  function metrics(model) {
    return `<div class="metrics"><div><span class="metric-label">Память</span><span class="metric-value">${number(model.requirements.memory_mb)}<span class="metric-unit">МБ</span></span></div><div><span class="metric-label">Задержка</span><span class="metric-value">${number(model.requirements.latency_ms)}<span class="metric-unit">мс</span></span></div><div><span class="metric-label">F1-score</span><span class="metric-value">${number(model.evaluation.f1, 3)}</span></div></div>`;
  }
  function tags(model) {
    return `<div class="tags">${model.signals.map((signal) => `<span class="tag signal-tag">${escape(signals[signal] || signal)}</span>`).join("")}${model.tags.slice(0, 3).map((tag) => `<span class="tag">${escape(tag)}</span>`).join("")}</div>`;
  }
  function modelCard(model) {
    const rec = model.recommendation;
    const explanation = rec ? `<div class="recommendation-explanation"><span class="recommendation-badge${rec.strategy === "fallback" ? " baseline" : ""}">${rec.strategy === "collaborative" ? "По вашим интересам" : "По устройству"}</span><p>${escape(rec.reason)}</p>${rec.based_on.length ? `<small>На основе интереса к: ${rec.based_on.map((item) => escape(item.name)).join(", ")}</small>` : ""}</div>` : "";
    return `<article class="model-card"><div class="card-top"><span class="category">${escape(categories[model.category])}</span><span class="card-version">v${escape(model.version)}</span></div><h3>${escape(model.name)}</h3><p class="card-description">${escape(model.description)}</p>${tags(model)}${metrics(model)}${explanation}<div class="card-bottom">${model.synthetic ? '<span class="synthetic"><span class="red-dot"></span> Синтетические метрики</span>' : '<span class="synthetic">Метрики из описания модели</span>'}<button class="detail-button" data-model="${escape(model.id)}" aria-label="Подробнее: ${escape(model.name)}">Подробнее <span aria-hidden="true">↗</span></button></div></article>`;
  }

  function catalogQuery() {
    const query = new URLSearchParams();
    for (const [key, value] of new FormData($("#filters-form"))) {
      if (String(value).trim()) query.set(key, String(value).trim());
    }
    if ($("#search").value.trim()) query.set("q", $("#search").value.trim());
    query.set("limit", "12");
    return query.toString();
  }
  async function loadCatalog(append = false) {
    if (append && (state.catalogBusy || !state.catalogCursor)) return;
    if (!append && !$("#filters-form").reportValidity()) return;
    const request = ++state.catalogRequest;
    state.catalogBusy = true;
    if (!append) {
      state.catalog = [];
      state.catalogCursor = null;
      state.catalogQuery = catalogQuery();
      $("#catalog-grid").replaceChildren();
      $("#catalog-state").innerHTML = loading();
      $("#results-count").textContent = "Загружаем каталог…";
    }
    $("#catalog-more").disabled = true;
    $("#catalog-more").hidden = !append;
    const query = new URLSearchParams(state.catalogQuery);
    if (append) query.set("cursor", state.catalogCursor);
    try {
      const data = await api(`/models?${query}`, { auth: false });
      if (request !== state.catalogRequest) return;
      state.catalog.push(...data.items);
      state.catalogCursor = data.next_cursor;
      $("#catalog-grid").innerHTML = state.catalog.map(modelCard).join("");
      $("#catalog-state").innerHTML = state.catalog.length ? "" : empty("Моделей пока нет", "Попробуйте другой сигнал или ослабьте ограничения устройства.", "reset-filters", "Сбросить фильтры");
      $("#results-count").textContent = `Показано моделей: ${number(state.catalog.length, 0)}`;
      $("#catalog-more").hidden = !data.next_cursor;
    } catch (error) {
      if (request !== state.catalogRequest) return;
      if (append) { toast(error.message, true); $("#catalog-more").hidden = false; }
      else { showError("#catalog-state", error, "retry-catalog"); $("#results-count").textContent = "Каталог недоступен"; }
    } finally {
      if (request === state.catalogRequest) {
        state.catalogBusy = false;
        $("#catalog-more").disabled = false;
      }
    }
  }

  function renderAccount() {
    $("#account").innerHTML = state.user
      ? `<button class="account-name" data-action="profile" aria-label="Профиль: ${escape(state.user.display_name)}"><span class="avatar">${escape(state.user.display_name.slice(0, 1).toUpperCase())}</span><span class="name-text">${escape(state.user.display_name)}</span></button><button class="logout" data-action="logout">Выйти</button>`
      : '<button class="button button-dark button-small" data-action="login">Войти <span aria-hidden="true">↗</span></button>';
    $("#add-model").hidden = state.user?.role !== "admin";
  }
  function setAuthMode(mode) {
    if ($("#auth-submit").disabled) return;
    state.authMode = mode;
    const register = mode === "register";
    $("#auth-title").innerHTML = `${register ? "Начнём знакомство" : "С возвращением"}<span class="red">.</span>`;
    $("#auth-description").textContent = register ? "Создайте аккаунт для подбора моделей под ваше устройство." : "Войдите, чтобы подбирать модели и сохранять историю.";
    $("#register-name-field").hidden = !register;
    $("#auth-form").elements.display_name.required = register;
    $("#auth-form").elements.password.minLength = register ? 10 : 1;
    $("#auth-form").elements.password.autocomplete = register ? "new-password" : "current-password";
    $("#password-help").hidden = !register;
    $("#auth-submit").textContent = register ? "Создать аккаунт →" : "Войти →";
    $("#login-tab").classList.toggle("active", !register);
    $("#register-tab").classList.toggle("active", register);
    $("#login-tab").setAttribute("aria-pressed", String(!register));
    $("#register-tab").setAttribute("aria-pressed", String(register));
    setFormError("#auth-error");
  }
  function openAuth(after = null) {
    state.afterAuth = after;
    setAuthMode("login");
    if (!$("#auth-dialog").open) $("#auth-dialog").showModal();
  }
  function requireUser(operation) {
    if (!state.user) openAuth(operation);
    else operation();
  }
  async function submitAuth(event) {
    event.preventDefault();
    const form = event.currentTarget;
    await busy($("#auth-submit"), async () => {
      const mode = state.authMode;
      const tabs = [$("#login-tab"), $("#register-tab")];
      tabs.forEach((tab) => { tab.disabled = true; });
      setFormError("#auth-error");
      try {
        const values = Object.fromEntries(new FormData(form));
        if (mode === "register") {
          await api("/auth/register", { method: "POST", auth: false, body: values });
          // If the network fails during login, the newly created account can still be used.
          state.authMode = "login";
          toast("Аккаунт создан. Выполняем вход…");
        }
        const login = await api("/auth/token", { method: "POST", auth: false, form: true, body: { username: values.email, password: values.password } });
        const epoch = ++state.authEpoch;
        storeToken(login.access_token);
        const user = await api("/users/me");
        if (epoch !== state.authEpoch) return;
        state.user = user;
        renderAccount();
        $("#auth-dialog").close();
        form.reset();
        toast(`Вы вошли как ${user.display_name}`);
        const after = state.afterAuth;
        state.afterAuth = null;
        if ($("#model-dialog").open && state.detail) renderDetail(state.detail);
        if (after) after();
        else if (state.page !== "catalog") renderPage(state.page);
      } catch (error) { setFormError("#auth-error", error.message); }
      finally { tabs.forEach((tab) => { tab.disabled = false; }); }
    });
    const message = $("#auth-error").textContent;
    setAuthMode(state.authMode);
    setFormError("#auth-error", message);
  }

  function openProfile() {
    requireUser(() => {
      const form = $("#profile-form");
      const device = state.user.device || { signal: "eeg", memory_budget_mb: 128, max_latency_ms: 100, reference_device: "synthetic-edge-v1" };
      form.elements.display_name.value = state.user.display_name;
      for (const [key, value] of Object.entries(device)) form.elements[key].value = value;
      setFormError("#profile-error");
      if (!$("#profile-dialog").open) $("#profile-dialog").showModal();
    });
  }
  async function submitProfile(event) {
    event.preventDefault();
    const form = event.currentTarget;
    await busy($("button[type=submit]", form), async () => {
      const values = Object.fromEntries(new FormData(form));
      const epoch = state.authEpoch;
      setFormError("#profile-error");
      try {
        const user = await api("/users/me", { method: "PUT", body: {
          display_name: values.display_name,
          device: { signal: values.signal, memory_budget_mb: Number(values.memory_budget_mb), max_latency_ms: Number(values.max_latency_ms), reference_device: values.reference_device },
        } });
        if (epoch !== state.authEpoch) return;
        state.user = user;
        renderAccount();
        $("#profile-dialog").close();
        toast("Параметры устройства сохранены");
        navigate("recommendations");
      } catch (error) { setFormError("#profile-error", error.message); }
    });
  }

  async function loadRecommendations() {
    const request = ++state.recommendationsRequest;
    const epoch = state.authEpoch;
    $("#recommendations-grid").replaceChildren();
    $("#device-summary").replaceChildren();
    if (!state.user) {
      $("#recommendations-state").innerHTML = empty("Подбор начинается с вас", "Войдите и укажите параметры устройства, чтобы найти совместимые модели.", "login", "Войти в аккаунт");
      return;
    }
    if (!state.user.device) {
      $("#recommendations-state").innerHTML = empty("Расскажите об устройстве", "Выберите сигнал, бюджет памяти и допустимую задержку. Мы отфильтруем каталог по этим ограничениям.", "profile", "Настроить устройство");
      return;
    }
    const d = state.user.device;
    $("#device-summary").innerHTML = `<div class="device-strip"><span class="device-label"><span class="red-dot"></span> ${escape(d.reference_device)}</span><span>Сигнал<strong>${escape(signals[d.signal])}</strong></span><span>Память<strong>≤ ${number(d.memory_budget_mb)} МБ</strong></span><span>Задержка<strong>≤ ${number(d.max_latency_ms)} мс</strong></span></div>`;
    $("#recommendations-state").innerHTML = loading();
    try {
      const data = await api("/recommendations?limit=100");
      if (request !== state.recommendationsRequest || epoch !== state.authEpoch) return;
      $("#recommendations-grid").innerHTML = data.items.map(modelCard).join("");
      const fallbackMessages = {
        no_history: "Начните с оценок, сохранений или выбора моделей — так мы узнаем ваши предпочтения. Пока показываем совместимые модели.",
        no_positive_preferences: "Сохраните понравившиеся модели или поставьте им высокую оценку, чтобы настроить рекомендации.",
        no_collaborative_neighbors: "Пока недостаточно общих интересов с другими пользователями. Показываем совместимые модели по задержке.",
        insufficient_collaborative_candidates: "Сначала модели по вашим интересам; далее — дополнительные варианты по устройству.",
      };
      $("#recommendations-state").innerHTML = data.items.length ? `<div class="recommendation-summary" role="status"><strong>${data.collaborative_count ? `По вашим интересам: ${data.collaborative_count}` : "Знакомимся с вашими интересами"}</strong><p>${escape(fallbackMessages[data.fallback_reason] || "Порядок учитывает ваши действия и совместные предпочтения пользователей.")} Все модели соответствуют параметрам устройства.</p><small>Учебные данные и характеристики синтетические.</small></div>` : empty("Новых подходящих моделей пока нет", "Уже выбранные и оценённые модели исключены. Можно изменить параметры устройства или посмотреть каталог.", "catalog", "Открыть каталог");
    } catch (error) {
      if (request === state.recommendationsRequest && epoch === state.authEpoch) showError("#recommendations-state", error, "retry-recommendations");
    }
  }

  async function loadHistory(append = false) {
    const request = ++state.historyRequest;
    const epoch = state.authEpoch;
    if (!append) {
      state.history = [];
      state.historyCursor = null;
      $("#history-list").replaceChildren();
      $("#history-more").hidden = true;
    }
    if (!state.user) {
      $("#history-state").innerHTML = empty("Ваша история — в вашем аккаунте", "Войдите, чтобы увидеть просмотренные модели, сохранения и оценки.", "login", "Войти в аккаунт");
      return;
    }
    if (!append) $("#history-state").innerHTML = loading();
    $("#history-more").disabled = true;
    const query = new URLSearchParams({ limit: "20" });
    if (append && state.historyCursor) query.set("cursor", state.historyCursor);
    try {
      const data = await api(`/users/me/history?${query}`);
      if (request !== state.historyRequest || epoch !== state.authEpoch) return;
      state.history.push(...data.items);
      state.historyCursor = data.next_cursor;
      $("#history-state").innerHTML = state.history.length ? "" : empty("Здесь появится ваша история", "Откройте модель в каталоге, сохраните её или поставьте оценку.", "catalog", "Перейти в каталог");
      $("#history-list").innerHTML = state.history.map((item) => `<article class="history-row"><span class="event-icon" aria-hidden="true">${eventIcons[item.type] || "↗"}</span><div><h3>${escape(item.model_snapshot.name)}</h3><p>v${escape(item.model_snapshot.version)}${item.type === "rating" ? ` · Оценка ${item.rating} из 5` : ""}</p></div><time class="history-date" datetime="${escape(item.created_at)}">${escape(dateFormat.format(new Date(item.created_at)))}</time><span class="history-type">${escape(events[item.type])}</span></article>`).join("");
      $("#history-more").hidden = !data.next_cursor;
    } catch (error) {
      if (request !== state.historyRequest || epoch !== state.authEpoch) return;
      if (append) toast(error.message, true);
      else showError("#history-state", error, "retry-history");
    } finally { if (request === state.historyRequest) $("#history-more").disabled = false; }
  }

  async function loadAnalytics() {
    const request = ++state.analyticsRequest;
    const epoch = state.authEpoch;
    $("#analytics-content").replaceChildren();
    if (!state.user) {
      $("#analytics-state").innerHTML = empty("Что выбирает сообщество", "Войдите, чтобы посмотреть популярные модели и пользовательские оценки.", "login", "Войти в аккаунт");
      return;
    }
    $("#analytics-state").innerHTML = loading();
    try {
      const [popular, ratings] = await Promise.all([api("/analytics/popular?days=30&limit=10"), api("/analytics/ratings")]);
      if (request !== state.analyticsRequest || epoch !== state.authEpoch) return;
      $("#analytics-state").replaceChildren();
      const panel = (title, caption, items, rating) => `<div class="analytics-panel"><h3>${title}</h3><p class="analytics-caption">${caption}</p>${items.length ? items.slice(0, 10).map((item, i) => `<div class="rank-row"><span class="rank-number">${String(i + 1).padStart(2, "0")}</span><button class="rank-name rank-open" data-model="${escape(item.model_id)}">${escape(item.name)}</button><span class="rank-value">${number(rating ? item.average_rating : item.events, rating ? 2 : 0)}${rating ? ' <span class="red">★</span>' : ""}<small>${rating ? `${number(item.voters, 0)} голосов` : "действий"}</small></span></div>`).join("") : '<p class="analytics-caption">Пока нет данных.</p>'}</div>`;
      $("#analytics-content").innerHTML = panel("Популярные модели", "Все действия пользователей · последние 30 дней", popular.items, false) + panel("Пользовательские оценки", "Последняя оценка каждого пользователя · за всё время", ratings.items, true);
    } catch (error) {
      if (request === state.analyticsRequest && epoch === state.authEpoch) showError("#analytics-state", error, "retry-analytics");
    }
  }

  function renderDetail(model) {
    state.detail = model;
    $("#model-detail").innerHTML = `<div class="detail-header"><span class="category">${escape(categories[model.category])}</span><span class="card-version">v${escape(model.version)}</span></div><h2 id="model-title">${escape(model.name)}<span class="red">.</span></h2>${tags(model)}<p class="model-description">${escape(model.description)}</p><div class="detail-metrics">${metrics(model)}</div><dl class="detail-data"><dt>Устройство</dt><dd>${escape(model.requirements.reference_device)}</dd><dt>Датасет</dt><dd>${escape(model.evaluation.dataset)}</dd><dt>Протокол оценки</dt><dd>${escape(model.evaluation.protocol)}</dd><dt>Идентификатор</dt><dd class="mono">${escape(model.slug)}</dd></dl>${model.synthetic ? '<p class="detail-notice">Синтетические характеристики для учебной демонстрации. F1, память и задержка не являются результатами реальных экспериментов.</p>' : ""}<div class="detail-actions"><button class="button button-outline" data-event="save">Сохранить <span aria-hidden="true">+</span></button><button class="button button-red" data-event="select">Выбрать модель <span aria-hidden="true">↗</span></button></div><div class="rating-row"><span>Ваша оценка</span><div class="rating-buttons" role="group" aria-label="Оценка модели">${[1, 2, 3, 4, 5].map((v) => `<button data-event="rating" data-rating="${v}" aria-label="Оценить на ${v} из 5">${v}</button>`).join("")}</div><span id="rating-status" role="status"></span></div><p class="form-help detail-help">${state.user ? "Сохранение и выбор добавляют запись в историю действий." : "Войдите, чтобы сохранять, выбирать и оценивать модели."}</p>${state.user?.role === "admin" ? '<div class="admin-actions"><button class="text-button" data-action="edit-model">Редактировать ↗</button><button class="text-button danger-text" data-action="archive-model">Архивировать</button></div><div id="archive-confirm" class="archive-confirm" hidden>Модель исчезнет из каталога. История действий сохранится.<br><button class="button button-red button-small" data-action="confirm-archive">Подтвердить архивирование</button></div>' : ""}`;
  }

  async function openModel(id) {
    const request = ++state.detailRequest;
    state.detail = null;
    $("#model-detail").innerHTML = `<h2 id="model-title">Карточка модели</h2>${loading()}`;
    if (!$("#model-dialog").open) $("#model-dialog").showModal();
    try {
      const model = await api(`/models/${encodeURIComponent(id)}`, { auth: false });
      if (request !== state.detailRequest || !$("#model-dialog").open) return;
      renderDetail(model);
      if (state.user) {
        try { await recordEvent(model.id, "view"); }
        catch (error) { toast(`Просмотр не записан: ${error.message}`, true); }
      }
    } catch (error) {
      if (request === state.detailRequest && $("#model-dialog").open) $("#model-detail").innerHTML = `<h2 id="model-title">Модель недоступна</h2>${empty("Не удалось открыть", error.message)}`;
    }
  }

  async function recordEvent(modelId, type, rating) {
    const key = `${modelId}:${type}:${rating ?? ""}`;
    // Keep the UUID after a lost response, so a retry cannot insert the same event twice.
    let body = state.pendingEvents.get(key);
    if (!body) {
      body = { model_id: modelId, type, request_id: crypto.randomUUID() };
      if (type === "rating") body.rating = rating;
      state.pendingEvents.set(key, body);
    }
    const result = await api("/interactions", { method: "POST", body });
    state.pendingEvents.delete(key);
    return result;
  }
  async function interact(button) {
    if (!state.detail) return;
    const model = state.detail;
    const type = button.dataset.event;
    const rating = type === "rating" ? Number(button.dataset.rating) : undefined;
    requireUser(() => {
      const currentButton = button.isConnected ? button : $(`[data-event="${type}"]${rating ? `[data-rating="${rating}"]` : ""}`, $("#model-detail"));
      if (!currentButton) return;
      return busy(currentButton, async () => {
      const epoch = state.authEpoch;
      const detail = $("#model-detail");
      let status = $("#interaction-status", detail);
      if (!status) {
        status = document.createElement("p");
        status.id = "interaction-status";
        status.className = "interaction-status";
        status.setAttribute("role", "status");
        $(".detail-actions", detail).after(status);
      }
      status.classList.remove("error");
      status.textContent = "Записываем действие…";
      const related = type === "rating" ? $$(".rating-buttons button") : [];
      related.forEach((b) => { b.disabled = true; });
      try {
        await recordEvent(model.id, type, rating);
        if (epoch !== state.authEpoch) return;
        if (type === "rating") {
          if (state.detail?.id === model.id && $("#model-dialog").open) {
            $$(".rating-buttons button").forEach((b) => {
              const chosen = Number(b.dataset.rating) === rating;
              b.classList.toggle("chosen", chosen);
              b.setAttribute("aria-pressed", String(chosen));
            });
            $("#rating-status").textContent = `${rating} из 5 — записано`;
          }
          toast("Ваша оценка сохранена");
        }
        status.textContent = type === "rating" ? "Ваша оценка сохранена" : type === "save" ? "Сохранение добавлено в историю" : "Выбор модели добавлен в историю";
        if (type !== "rating") toast(status.textContent);
        if (state.page === "history") loadHistory();
        if (state.page === "analytics") loadAnalytics();
        if (state.page === "recommendations") loadRecommendations();
      } catch (error) {
        status.classList.add("error");
        status.textContent = error.message;
        toast(error.message, true);
      }
      finally { related.forEach((b) => { b.disabled = false; }); }
      });
    });
  }

  function openEditor(model = null) {
    if (state.user?.role !== "admin") return;
    state.editing = model?.id || null;
    const form = $("#editor-form");
    form.reset();
    const values = model || { name: "", slug: "", version: "1.0", description: "", category: "classical_ml", tags: [], signals: ["eeg"], synthetic: true, requirements: { memory_mb: "", latency_ms: "", reference_device: "synthetic-edge-v1" }, evaluation: { f1: "", dataset: "synthetic-v1", protocol: "Simulated values, not real experimental results" } };
    for (const field of ["name", "slug", "version", "description", "category"]) form.elements[field].value = values[field];
    form.elements.tags.value = values.tags.join(", ");
    $$("input[name=signals]", form).forEach((input) => { input.checked = values.signals.includes(input.value); });
    for (const [key, value] of Object.entries(values.requirements)) form.elements[key].value = value;
    for (const [key, value] of Object.entries(values.evaluation)) form.elements[key].value = value;
    form.elements.synthetic.checked = values.synthetic;
    $("#editor-title").innerHTML = `${model ? "Редактировать модель" : "Новая модель"}<span class="red">.</span>`;
    setFormError("#editor-error");
    if ($("#model-dialog").open) $("#model-dialog").close();
    $("#editor-dialog").showModal();
  }
  async function submitEditor(event) {
    event.preventDefault();
    const form = event.currentTarget;
    await busy($("button[type=submit]", form), async () => {
      setFormError("#editor-error");
      const data = new FormData(form);
      const values = Object.fromEntries(data);
      if (!data.getAll("signals").length) { setFormError("#editor-error", "Выберите хотя бы один сигнал."); return; }
      const body = {
        name: values.name, slug: values.slug, version: values.version, description: values.description,
        category: values.category, signals: data.getAll("signals"),
        tags: [...new Set(values.tags.split(",").map((s) => s.trim()).filter(Boolean))],
        requirements: { memory_mb: Number(values.memory_mb), latency_ms: Number(values.latency_ms), reference_device: values.reference_device },
        evaluation: { f1: Number(values.f1), dataset: values.dataset, protocol: values.protocol },
        synthetic: form.elements.synthetic.checked,
      };
      try {
        await api(state.editing ? `/models/${encodeURIComponent(state.editing)}` : "/models", { method: state.editing ? "PUT" : "POST", body });
        $("#editor-dialog").close();
        toast("Модель сохранена");
        loadCatalog();
        if (state.page === "recommendations") loadRecommendations();
        if (state.page === "analytics") loadAnalytics();
      } catch (error) { setFormError("#editor-error", error.message); }
    });
  }
  async function archiveModel(button) {
    if (!state.detail) return;
    const id = state.detail.id;
    await busy(button, async () => {
      try {
        await api(`/models/${encodeURIComponent(id)}`, { method: "DELETE" });
        $("#model-dialog").close();
        toast("Модель архивирована. История сохранена.");
        loadCatalog();
        if (state.page === "recommendations") loadRecommendations();
        if (state.page === "analytics") loadAnalytics();
      } catch (error) { toast(error.message, true); }
    });
  }

  const pages = ["catalog", "recommendations", "history", "analytics"];
  function renderPage(page) {
    state.page = pages.includes(page) ? page : "catalog";
    pages.forEach((name) => { $(`#page-${name}`).hidden = name !== state.page; });
    $("#hero").hidden = state.page !== "catalog";
    $$(".nav-link").forEach((button) => {
      const active = button.dataset.page === state.page;
      button.classList.toggle("active", active);
      if (active) button.setAttribute("aria-current", "page");
      else button.removeAttribute("aria-current");
    });
    const titles = { catalog: "Каталог моделей", recommendations: "Персональный подбор", history: "История действий", analytics: "Аналитика" };
    document.title = `${titles[state.page]} — Edge Catalog`;
    if (state.page === "recommendations") loadRecommendations();
    if (state.page === "history") loadHistory();
    if (state.page === "analytics") loadAnalytics();
  }
  function navigate(page) {
    if (location.hash.slice(1) === page) {
      renderPage(page);
      focusPage();
    }
    else location.hash = page;
  }
  function focusPage() {
    const heading = $(`#page-${state.page} h1, #page-${state.page} h2`);
    heading.tabIndex = -1;
    heading.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }
  function resetFilters() {
    $("#filters-form").reset();
    $("#search-form").reset();
    loadCatalog();
  }

  document.addEventListener("click", (event) => {
    if (event.target.closest(".skip-link")) {
      event.preventDefault();
      $("#main").focus();
      $("#main").scrollIntoView();
      return;
    }
    const button = event.target.closest("button");
    if (!button || button.disabled) return;
    if (button.hasAttribute("data-close")) { button.closest("dialog").close(); return; }
    if (button.dataset.page) { navigate(button.dataset.page); return; }
    if (button.dataset.model) { openModel(button.dataset.model); return; }
    if (button.dataset.event) { interact(button); return; }
    switch (button.dataset.action) {
      case "login": openAuth(); break;
      case "profile": openProfile(); break;
      case "logout": forgetSession(); $$("dialog[open]").forEach((dialog) => dialog.close()); navigate("catalog"); toast("Вы вышли из аккаунта"); break;
      case "catalog": navigate("catalog"); break;
      case "retry-catalog": loadCatalog(); break;
      case "retry-recommendations": loadRecommendations(); break;
      case "retry-history": loadHistory(); break;
      case "retry-analytics": loadAnalytics(); break;
      case "reset-filters": resetFilters(); break;
      case "edit-model": openEditor(state.detail); break;
      case "archive-model": $("#archive-confirm").hidden = false; break;
      case "confirm-archive": archiveModel(button); break;
    }
  });
  $("#filters-form").addEventListener("submit", (event) => { event.preventDefault(); loadCatalog(); });
  $("#search-form").addEventListener("submit", (event) => { event.preventDefault(); loadCatalog(); });
  $("#search").addEventListener("search", () => { if (!$("#search").value) loadCatalog(); });
  $("#reset-filters").addEventListener("click", resetFilters);
  $("#catalog-more").addEventListener("click", () => loadCatalog(true));
  $("#history-more").addEventListener("click", () => { if (!$("#history-more").disabled) loadHistory(true); });
  $("#refresh-history").addEventListener("click", () => loadHistory());
  $("#refresh-recommendations").addEventListener("click", () => loadRecommendations());
  $("#refresh-analytics").addEventListener("click", loadAnalytics);
  $("#hero-cta").addEventListener("click", () => { requireUser(openProfile); });
  $("#login-tab").addEventListener("click", () => setAuthMode("login"));
  $("#register-tab").addEventListener("click", () => setAuthMode("register"));
  $("#auth-form").addEventListener("submit", submitAuth);
  $("#profile-form").addEventListener("submit", submitProfile);
  $("#editor-form").addEventListener("submit", submitEditor);
  $("#add-model").addEventListener("click", () => openEditor());
  $("#model-dialog").addEventListener("close", () => { state.detailRequest += 1; });
  $("#auth-dialog").addEventListener("close", () => { $("#auth-form").elements.password.value = ""; });
  $$("dialog").forEach((dialog) => dialog.addEventListener("click", (event) => {
    if (event.target !== dialog) return;
    const rect = dialog.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) dialog.close();
  }));
  window.addEventListener("hashchange", () => {
    if (location.hash === "#main") { $("#main").focus(); return; }
    renderPage(location.hash.slice(1));
    focusPage();
  });

  async function start() {
    renderAccount();
    loadCatalog();
    if (state.token) {
      const epoch = state.authEpoch;
      try {
        const user = await api("/users/me");
        if (epoch === state.authEpoch) { state.user = user; renderAccount(); }
      } catch (error) {
        if (epoch === state.authEpoch && error.status !== 401) toast(error.message, true);
      }
    }
    renderPage(location.hash.slice(1));
  }
  start();
})();
