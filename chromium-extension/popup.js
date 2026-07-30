const api = globalThis.browser ?? globalThis.chrome;
const DEFAULT_BROKER = "http://127.0.0.1:17871";
const $ = id => document.getElementById(id);

async function getState(defaults) { return await api.storage.local.get(defaults); }
async function setState(values) { await api.storage.local.set(values); }

function permissionPattern(raw) {
  const url = new URL(raw);
  if (!["http:", "https:"].includes(url.protocol)) throw new Error("Yalnız http/https URL.");
  return `${url.protocol}//${url.host}/*`;
}

async function render() {
  const state = await getState({
    brokerUrl: DEFAULT_BROKER, profileLabel: "", pairedAt: "", sites: []
  });
  $("brokerUrl").value = state.brokerUrl;
  $("profileLabel").value = state.profileLabel;
  $("pairStatus").textContent = state.pairedAt ? `Eşleşti: ${state.pairedAt}` : "Eşleşmemiş";
  const container = $("sites");
  container.textContent = "";
  for (const site of state.sites) {
    const item = document.createElement("div");
    item.className = "site";
    const title = document.createElement("strong");
    title.textContent = `${site.name} — ${site.lastStatus || "PENDING"}`;
    const meta = document.createElement("div");
    meta.className = "muted";
    meta.textContent = `${site.url}\nCookie: ${site.cookieCount ?? "?"} | Son: ${site.lastSync || "-"}${site.lastError ? `\nHata: ${site.lastError}` : ""}`;
    const actions = document.createElement("div");
    actions.className = "actions";
    const sync = document.createElement("button");
    sync.textContent = "Eşitle";
    sync.onclick = async () => {
      await api.runtime.sendMessage({type:"SYNC_ONE", name:site.name});
      await render();
    };
    const remove = document.createElement("button");
    remove.textContent = "Sil";
    remove.className = "danger";
    remove.onclick = async () => {
      const current = await getState({sites:[]});
      await setState({sites:current.sites.filter(x => x.name !== site.name)});
      await render();
    };
    actions.append(sync, remove);
    item.append(title, meta, actions);
    container.append(item);
  }
}

$("pairButton").onclick = async () => {
  try {
    const brokerUrl = $("brokerUrl").value.trim().replace(/\/+$/, "");
    const label = $("profileLabel").value.trim();
    const code = $("pairCode").value.trim();
    const result = await api.runtime.sendMessage({
      type:"PAIR", payload:{brokerUrl, label, code}
    });
    $("pairStatus").textContent = `Eşleştirme başarılı: ${result.paired_at}`;
    await render();
  } catch (error) {
    $("pairStatus").textContent = `HATA: ${error.message || error}`;
  }
};

$("addButton").onclick = async () => {
  try {
    const name = $("siteName").value.trim();
    const url = new URL($("siteUrl").value.trim()).toString();
    if (!/^[A-Za-z0-9._-]{1,100}$/.test(name)) throw new Error("Kayıt adı geçersiz.");
    const granted = await api.permissions.request({origins:[permissionPattern(url)]});
    if (!granted) throw new Error("Host izni verilmedi.");
    const keepaliveUrl = $("keepaliveUrl").value.trim();
    if (keepaliveUrl && new URL(keepaliveUrl).origin !== new URL(url).origin) {
      throw new Error("Keep-alive aynı origin üzerinde olmalı.");
    }
    const keepaliveMinutes = Number($("keepaliveMinutes").value || 0);
    if (keepaliveMinutes !== 0 && keepaliveMinutes < 5) throw new Error("Keep-alive minimum 5 dakika.");
    const state = await getState({sites:[]});
    if (state.sites.some(site => site.name === name)) throw new Error("Bu kayıt adı zaten var.");
    state.sites.push({
      name,
      url,
      storeId:$("storeId").value.trim(),
      keepaliveUrl,
      keepaliveMinutes,
      lastStatus:"PENDING"
    });
    await setState({sites:state.sites});
    await api.runtime.sendMessage({type:"SYNC_ONE", name});
    $("addStatus").textContent = "Eklendi ve eşitlendi.";
    await render();
  } catch (error) {
    $("addStatus").textContent = `HATA: ${error.message || error}`;
  }
};

$("syncAllButton").onclick = async () => {
  try {
    await api.runtime.sendMessage({type:"SYNC_ALL"});
    await render();
  } catch (error) {
    $("addStatus").textContent = `HATA: ${error.message || error}`;
  }
};

render();
