"use strict";

const DB_NAME = "mosrechnung-web";
const DB_VERSION = 1;
const BACKUP_FORMAT = "mosrechnung-backup";
const BACKUP_VERSION = 1;
const MAX_BACKUP_BYTES = 25 * 1024 * 1024;
const DEFAULT_SETTINGS = {
  companyName: "",
  companyAddress: "",
  companySeat: "",
  companyIban: "",
  companyBic: "",
  companyTaxOffice: "",
  companyTaxNumber: "",
  companyVatId: "",
  companyPhone: "",
  companyEmail: "",
  companyLogo: "",
  invoicePattern: "RG{number:03d}/{year}",
  nextInvoiceNumber: 1,
  taxRate: 19,
};

const state = {
  db: null,
  customers: [],
  services: [],
  invoices: [],
  settings: { ...DEFAULT_SETTINGS },
};

const moneyFormatter = new Intl.NumberFormat("de-DE", { style: "currency", currency: "EUR" });

function openDb() {
  return new Promise((resolve, reject) => {
    const request = indexedDB.open(DB_NAME, DB_VERSION);
    request.onupgradeneeded = () => {
      const db = request.result;
      if (!db.objectStoreNames.contains("customers")) {
        db.createObjectStore("customers", { keyPath: "id", autoIncrement: true });
      }
      if (!db.objectStoreNames.contains("services")) {
        db.createObjectStore("services", { keyPath: "id", autoIncrement: true });
      }
      if (!db.objectStoreNames.contains("invoices")) {
        db.createObjectStore("invoices", { keyPath: "id", autoIncrement: true });
      }
      if (!db.objectStoreNames.contains("settings")) {
        db.createObjectStore("settings", { keyPath: "key" });
      }
    };
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function store(name, mode = "readonly") {
  return state.db.transaction(name, mode).objectStore(name);
}

function getAll(name) {
  return new Promise((resolve, reject) => {
    const request = store(name).getAll();
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function put(name, value) {
  return new Promise((resolve, reject) => {
    const request = store(name, "readwrite").put(value);
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function remove(name, id) {
  return new Promise((resolve, reject) => {
    const request = store(name, "readwrite").delete(Number(id));
    request.onsuccess = () => resolve();
    request.onerror = () => reject(request.error);
  });
}

function getSettings() {
  return new Promise((resolve, reject) => {
    const request = store("settings").get("settings");
    request.onsuccess = () => resolve({ ...DEFAULT_SETTINGS, ...(request.result?.value || {}) });
    request.onerror = () => reject(request.error);
  });
}

function saveSettings(settings) {
  return put("settings", { key: "settings", value: settings });
}

function centsFromText(text) {
  const normalized = String(text).trim().replace(/\./g, "").replace(",", ".");
  const value = Number.parseFloat(normalized);
  if (!Number.isFinite(value) || value < 0) {
    throw new Error("Bitte einen gueltigen Betrag eingeben.");
  }
  return Math.round(value * 100);
}

function textFromCents(cents) {
  return (Number(cents || 0) / 100).toLocaleString("de-DE", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

function money(cents) {
  return moneyFormatter.format(Number(cents || 0) / 100);
}

function formatInvoiceNumber(pattern, sequence, invoiceDate) {
  const year = new Date(invoiceDate).getFullYear();
  return pattern
    .replace("{year}", String(year))
    .replace("{number:03d}", String(sequence).padStart(3, "0"))
    .replace("{number}", String(sequence));
}

function today() {
  return new Date().toISOString().slice(0, 10);
}

function normalize(text) {
  return String(text || "").normalize("NFKC").trim().replace(/\s+/g, " ").toLocaleLowerCase("de-DE");
}

let toastTimer;
function notify(message) {
  const toast = document.querySelector("#toast");
  toast.textContent = message;
  toast.classList.add("visible");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => toast.classList.remove("visible"), 3500);
}

async function loadState() {
  state.settings = await getSettings();
  state.customers = (await getAll("customers")).sort((a, b) => a.name.localeCompare(b.name, "de"));
  state.services = (await getAll("services")).sort((a, b) => a.description.localeCompare(b.description, "de"));
  state.invoices = (await getAll("invoices")).sort((a, b) => String(b.invoiceDate).localeCompare(String(a.invoiceDate)) || b.id - a.id);
}

function customerAddress(customer) {
  return [customer.street, [customer.postalCode, customer.city].filter(Boolean).join(" ")].filter(Boolean).join("\n");
}

function customerLabel(customer) {
  return customer.dogs ? `${customer.name} - ${customer.dogs}` : customer.name;
}

function renderCustomers() {
  const query = normalize(document.querySelector("#customerSearch").value);
  const list = document.querySelector("#customerList");
  const customers = state.customers.filter((customer) => {
    return !query || normalize(`${customer.name} ${customer.dogs}`).includes(query);
  });
  list.innerHTML = customers.map((customer) => `
    <article class="card">
      <div class="card-title">
        <strong>${escapeHtml(customer.name)}</strong>
        <span class="muted">${escapeHtml(customer.dogs || "")}</span>
      </div>
      <div>${escapeHtml(customerAddress(customer)).replace(/\n/g, "<br>")}</div>
      ${customer.phone ? `<div class="muted">${escapeHtml(customer.phone)}</div>` : ""}
      <div class="card-actions">
        <button type="button" data-customer-invoice="${customer.id}">Neue Rechnung</button>
        <button type="button" data-edit-customer="${customer.id}">Bearbeiten</button>
        <button type="button" data-delete-customer="${customer.id}">Loeschen</button>
      </div>
    </article>
  `).join("") || `<p class="muted">Keine Kunden gefunden.</p>`;
}

function renderServices() {
  const list = document.querySelector("#serviceList");
  list.innerHTML = state.services.map((service) => `
    <article class="card">
      <div class="card-title">
        <strong>${escapeHtml(service.description)}</strong>
        <span>${money(service.priceCents)}</span>
      </div>
      <div class="card-actions">
        <button type="button" data-edit-service="${service.id}">Bearbeiten</button>
        <button type="button" data-delete-service="${service.id}">Loeschen</button>
      </div>
    </article>
  `).join("") || `<p class="muted">Noch keine Leistungen angelegt.</p>`;
}

function renderInvoices() {
  const query = normalize(document.querySelector("#invoiceSearch").value);
  const list = document.querySelector("#invoiceList");
  const invoices = state.invoices.filter((invoice) => {
    return !query || normalize(`${invoice.number} ${invoice.customerName}`).includes(query);
  });
  list.innerHTML = invoices.map((invoice) => `
    <article class="card">
      <div class="card-title">
        <strong>${escapeHtml(invoice.number)}</strong>
        <span>${money(invoice.totalCents)}</span>
      </div>
      <div>${escapeHtml(invoice.customerName)}</div>
      <div class="muted">${new Date(invoice.invoiceDate).toLocaleDateString("de-DE")}</div>
      <div class="card-actions">
        <button type="button" data-print-invoice="${invoice.id}">PDF/Drucken</button>
        <button type="button" data-edit-invoice="${invoice.id}">Bearbeiten</button>
        <button type="button" data-delete-invoice="${invoice.id}">Loeschen</button>
      </div>
    </article>
  `).join("") || `<p class="muted">Noch keine Rechnungen angelegt.</p>`;
}

function renderSettings() {
  const form = document.querySelector("#settingsForm");
  Object.entries(state.settings).forEach(([key, value]) => {
    const field = form.elements[key];
    if (field && field.type !== "file") {
      field.value = value;
    }
  });
}

function renderAll() {
  renderCustomers();
  renderServices();
  renderInvoices();
  renderSettings();
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#39;",
  })[char]);
}

function showDialog(dialog) {
  if (typeof dialog.showModal === "function") {
    dialog.showModal();
  } else {
    dialog.setAttribute("open", "");
  }
}

function closeDialog(dialog) {
  dialog.close?.();
  dialog.removeAttribute("open");
}

function openCustomerDialog(customer = {}) {
  const form = document.querySelector("#customerForm");
  form.reset();
  ["id", "name", "street", "postalCode", "city", "phone", "dogs"].forEach((key) => {
    form.elements[key].value = customer[key] || "";
  });
  showDialog(document.querySelector("#customerDialog"));
}

function openServiceDialog(service = {}) {
  const form = document.querySelector("#serviceForm");
  form.reset();
  form.elements.id.value = service.id || "";
  form.elements.description.value = service.description || "";
  form.elements.price.value = service.id ? textFromCents(service.priceCents) : "";
  showDialog(document.querySelector("#serviceDialog"));
}

function fillCustomerSelect(selectedId = "") {
  const form = document.querySelector("#invoiceForm");
  document.querySelector("#customerSuggestions").innerHTML = state.customers.map((customer) => (
    `<option value="${escapeHtml(customerLabel(customer))}"></option>`
  )).join("");
  form.elements.customerId.value = "";
  form.elements.customerSearch.value = "";
}

function resolveCustomerInput() {
  const form = document.querySelector("#invoiceForm");
  const query = normalize(form.elements.customerSearch.value);
  const matches = state.customers.filter((customer) => (
    normalize(customerLabel(customer)) === query || normalize(customer.name) === query
  ));
  form.elements.customerId.value = matches.length === 1 ? String(matches[0].id) : "";
  return matches.length === 1 ? matches[0] : null;
}

function addInvoiceItem(item = {}) {
  const template = document.querySelector("#invoiceItemTemplate");
  const node = template.content.firstElementChild.cloneNode(true);
  const serviceSelect = node.querySelector("[name=serviceId]");
  const description = node.querySelector("[name=description]");
  const unitPrice = node.querySelector("[name=unitPrice]");
  serviceSelect.innerHTML = `<option value="">Individuell</option>` + state.services.map((service) => `
    <option value="${service.id}">${escapeHtml(service.description)}</option>
  `).join("");
  const isStoredItem = item.serviceId != null || item.description != null || item.unitPriceCents != null;
  const defaultService = isStoredItem ? null : state.services[0];
  serviceSelect.value = item.serviceId || defaultService?.id || "";
  const selectedService = state.services.find((service) => String(service.id) === serviceSelect.value);
  description.value = item.description ?? selectedService?.description ?? "";
  node.querySelector("[name=quantity]").value = item.quantity || 1;
  unitPrice.value = item.unitPriceCents != null
    ? textFromCents(item.unitPriceCents)
    : selectedService ? textFromCents(selectedService.priceCents) : "";

  const updateDescriptionVisibility = () => {
    const usesPreset = state.services.some((service) => String(service.id) === serviceSelect.value);
    description.hidden = usesPreset;
    description.required = !usesPreset;
  };
  updateDescriptionVisibility();
  serviceSelect.addEventListener("change", () => {
    const service = state.services.find((entry) => String(entry.id) === serviceSelect.value);
    if (service) {
      description.value = service.description;
      unitPrice.value = textFromCents(service.priceCents);
    }
    updateDescriptionVisibility();
    updateInvoiceTotal();
  });
  node.querySelectorAll("input").forEach((input) => input.addEventListener("input", updateInvoiceTotal));
  node.querySelector("[data-remove]").addEventListener("click", () => {
    node.remove();
    updateInvoiceTotal();
  });
  document.querySelector("#invoiceItems").append(node);
  updateInvoiceTotal();
}

function collectInvoiceItems() {
  return [...document.querySelectorAll(".invoice-item")].map((row) => {
    const quantity = Number(row.querySelector("[name=quantity]").value || 1);
    const unitPriceCents = centsFromText(row.querySelector("[name=unitPrice]").value);
    return {
      serviceId: row.querySelector("[name=serviceId]").value ? Number(row.querySelector("[name=serviceId]").value) : null,
      description: row.querySelector("[name=description]").value.trim(),
      quantity,
      unitPriceCents,
      totalCents: quantity * unitPriceCents,
    };
  });
}

function calculateTotals(items, taxRate) {
  const netCents = items.reduce((sum, item) => sum + item.totalCents, 0);
  const taxCents = Math.round(netCents * Number(taxRate || 0) / 100);
  return { netCents, taxCents, totalCents: netCents + taxCents };
}

function updateInvoiceTotal() {
  try {
    const items = collectInvoiceItems();
    const totals = calculateTotals(items, state.settings.taxRate);
    document.querySelector("#invoiceTotal").textContent =
      `Netto: ${money(totals.netCents)} · USt. ${state.settings.taxRate} %: ${money(totals.taxCents)} · Brutto: ${money(totals.totalCents)}`;
  } catch {
    document.querySelector("#invoiceTotal").textContent = "Bitte Beträge prüfen.";
  }
}

function openInvoiceDialog(invoice = {}, customerId = "") {
  if (!state.customers.length) {
    alert("Bitte zuerst mindestens einen Kunden anlegen.");
    return;
  }
  if (!state.services.length) {
    alert("Bitte zuerst mindestens eine Leistung anlegen.");
    return;
  }
  const form = document.querySelector("#invoiceForm");
  form.reset();
  document.querySelector("#invoiceItems").innerHTML = "";
  fillCustomerSelect(invoice.customerId || customerId);
  form.elements.id.value = invoice.id || "";
  form.elements.invoiceDate.value = invoice.invoiceDate || today();
  form.elements.number.value = invoice.number || formatInvoiceNumber(
    state.settings.invoicePattern,
    Number(state.settings.nextInvoiceNumber || 1),
    form.elements.invoiceDate.value,
  );
  (invoice.items || [{}]).forEach(addInvoiceItem);
  showDialog(document.querySelector("#invoiceDialog"));
}

async function saveCustomer(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const customer = Object.fromEntries(new FormData(form).entries());
  if (customer.id) customer.id = Number(customer.id);
  else delete customer.id;
  const duplicate = state.customers.find((entry) => (
    normalize(entry.name) === normalize(customer.name) && entry.id !== customer.id
  ));
  if (duplicate) {
    alert(`Ein Kunde mit dem Namen „${duplicate.name}“ ist bereits vorhanden.`);
    return;
  }
  await put("customers", customer);
  closeDialog(document.querySelector("#customerDialog"));
  await loadState();
  renderAll();
  notify("Kunde gespeichert.");
}

async function saveService(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const service = {
    description: form.elements.description.value.trim(),
    priceCents: centsFromText(form.elements.price.value),
  };
  if (form.elements.id.value) service.id = Number(form.elements.id.value);
  await put("services", service);
  closeDialog(document.querySelector("#serviceDialog"));
  await loadState();
  renderAll();
  notify("Leistung gespeichert.");
}

async function saveInvoice(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const customer = resolveCustomerInput();
  const items = collectInvoiceItems();
  const duplicate = state.invoices.find((entry) => {
    return entry.number === form.elements.number.value.trim() && String(entry.id) !== String(form.elements.id.value || "");
  });
  if (duplicate) {
    alert("Diese Rechnungsnummer ist bereits vergeben.");
    return;
  }
  if (!customer || items.length === 0) {
    alert("Bitte einen vorhandenen Kunden vollständig eingeben und mindestens eine Position erfassen.");
    return;
  }
  const totals = calculateTotals(items, state.settings.taxRate);
  const id = form.elements.id.value ? Number(form.elements.id.value) : undefined;
  const invoice = {
    id,
    number: form.elements.number.value.trim(),
    invoiceDate: form.elements.invoiceDate.value,
    customerId: customer.id,
    customerName: customer.name,
    customerAddress: customerAddress(customer),
    customerPhone: customer.phone || "",
    customerDogs: customer.dogs || "",
    items,
    taxRate: Number(state.settings.taxRate || 0),
    ...totals,
    createdAt: id ? state.invoices.find((entry) => entry.id === id)?.createdAt : new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  Object.keys(invoice).forEach((key) => invoice[key] === undefined && delete invoice[key]);
  await put("invoices", invoice);
  if (!id) {
    state.settings.nextInvoiceNumber = Number(state.settings.nextInvoiceNumber || 1) + 1;
    await saveSettings(state.settings);
  }
  closeDialog(document.querySelector("#invoiceDialog"));
  await loadState();
  renderAll();
  notify("Rechnung gespeichert.");
}

async function handleSettings(event) {
  event.preventDefault();
  const form = event.currentTarget;
  const next = { ...state.settings };
  for (const [key, value] of new FormData(form).entries()) {
    if (key !== "companyLogo") {
      next[key] = value;
    }
  }
  next.nextInvoiceNumber = Number(next.nextInvoiceNumber || 1);
  next.taxRate = Number(next.taxRate || 0);
  const file = form.elements.companyLogo.files?.[0];
  if (file) {
    if (!new Set(["image/png", "image/jpeg", "image/webp"]).has(file.type)) {
      alert("Bitte ein Logo als PNG, JPEG oder WebP auswählen.");
      return;
    }
    if (file.size > 5 * 1024 * 1024) {
      alert("Das Logo darf höchstens 5 MB groß sein.");
      return;
    }
    next.companyLogo = await fileToDataUrl(file);
  }
  await saveSettings(next);
  await loadState();
  renderAll();
  notify("Einstellungen gespeichert.");
}

function fileToDataUrl(file) {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result);
    reader.onerror = () => reject(reader.error);
    reader.readAsDataURL(file);
  });
}

function renderInvoicePrint(invoice) {
  const settings = state.settings;
  const missing = [
    ["companyName", "Firmenname"],
    ["companyIban", "IBAN"],
    ["companyVatId", "Umsatzsteuer-ID"],
  ].filter(([key]) => !String(settings[key] || "").trim());
  if (missing.length) {
    alert(`Bitte zuerst Einstellungen ausfuellen: ${missing.map((entry) => entry[1]).join(", ")}`);
    return;
  }
  document.querySelector("#printArea").innerHTML = `
    <article class="invoice-print">
      <section class="print-recipient">
        <strong>${escapeHtml(invoice.customerName)}</strong>
        ${invoice.customerDogs ? `<br><small>Hund: ${escapeHtml(invoice.customerDogs)}</small>` : ""}
        <br>${escapeHtml(invoice.customerAddress).replace(/\n/g, "<br>")}
      </section>
      <section class="print-meta">
        <h1>Rechnung ${escapeHtml(invoice.number)}</h1>
        <div>Rechnungsdatum<br><strong>${new Date(invoice.invoiceDate).toLocaleDateString("de-DE")}</strong></div>
      </section>
      <p>Für die folgenden Leistungen berechnen wir:</p>
      <table class="print-table">
        <thead><tr><th>Leistung</th><th class="number">Anzahl</th><th class="number">Einzelpreis</th><th class="number">Gesamt</th></tr></thead>
        <tbody>
          ${invoice.items.map((item) => `
            <tr>
              <td>${escapeHtml(item.description)}</td>
              <td class="number">${item.quantity}</td>
              <td class="number">${money(item.unitPriceCents)}</td>
              <td class="number">${money(item.totalCents)}</td>
            </tr>
          `).join("")}
        </tbody>
      </table>
      <section class="print-totals">
        <div><span>Nettobetrag</span><span>${money(invoice.netCents)}</span></div>
        <div><span>Umsatzsteuer ${invoice.taxRate} %</span><span>${money(invoice.taxCents)}</span></div>
        <div><strong>Bruttobetrag</strong><strong>${money(invoice.totalCents)}</strong></div>
      </section>
      <section class="print-payment-note">
        Lieferdatum entspricht Rechnungsdatum.<br>
        Zahlbar sofort ohne Abzug.<br>
        Bitte überweisen Sie den Gesamtbetrag auf das unten genannte Konto.
      </section>
      <footer class="print-footer">
        <span>${escapeHtml(settings.companyName)}</span>
        <span>IBAN ${escapeHtml(settings.companyIban)}</span>
        <span>USt-IdNr. ${escapeHtml(settings.companyVatId)}</span>
      </footer>
    </article>
  `;
}

function exportBackup() {
  const payload = JSON.stringify({
    format: BACKUP_FORMAT,
    version: BACKUP_VERSION,
    exportedAt: new Date().toISOString(),
    settings: state.settings,
    customers: state.customers,
    services: state.services,
    invoices: state.invoices,
  }, null, 2);
  const blob = new Blob([payload], { type: "application/json" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `mosrechnung-backup-${today()}.json`;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
  notify("Backup wurde zum Sichern übergeben.");
}

async function importBackup(file) {
  if (file.size > MAX_BACKUP_BYTES) throw new Error("Die Backup-Datei ist größer als 25 MB.");
  const payload = validateBackup(JSON.parse(await file.text()));
  if (!confirm("Vorhandene lokale Daten durch dieses Backup ersetzen?")) {
    return;
  }
  await replaceDatabase(payload);
  await loadState();
  renderAll();
  notify("Backup vollständig wiederhergestellt.");
}

function requireArray(value, name, maximum = 100000) {
  if (!Array.isArray(value) || value.length > maximum) {
    throw new Error(`Ungültiger Bereich im Backup: ${name}.`);
  }
  return value;
}

function requireText(value, name, maximum = 10000, allowEmpty = true) {
  if (typeof value !== "string" || value.length > maximum || (!allowEmpty && !value.trim())) {
    throw new Error(`Ungültiger Text im Backup: ${name}.`);
  }
  return value;
}

function requireId(value, name) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`Ungültige ID im Backup: ${name}.`);
  return value;
}

function validateBackup(payload) {
  if (!payload || typeof payload !== "object" || Array.isArray(payload)) {
    throw new Error("Die Backup-Datei hat nicht das erwartete Format.");
  }
  if (payload.format && payload.format !== BACKUP_FORMAT) throw new Error("Unbekanntes Backup-Format.");
  if (payload.version && payload.version > BACKUP_VERSION) throw new Error("Das Backup stammt aus einer neueren App-Version.");
  const customers = requireArray(payload.customers, "Kunden").map((entry, index) => ({
    id: requireId(entry?.id, `Kunde ${index + 1}`),
    name: requireText(entry.name, "Kundenname", 500, false),
    street: requireText(entry.street, "Straße", 500, false),
    postalCode: requireText(entry.postalCode, "PLZ", 20, false),
    city: requireText(entry.city, "Ort", 300, false),
    phone: requireText(entry.phone || "", "Telefon", 100),
    dogs: requireText(entry.dogs || "", "Hundename", 500),
  }));
  const customerIds = new Set(customers.map((entry) => entry.id));
  if (customerIds.size !== customers.length) throw new Error("Das Backup enthält doppelte Kunden-IDs.");
  const services = requireArray(payload.services, "Leistungen").map((entry, index) => ({
    id: requireId(entry?.id, `Leistung ${index + 1}`),
    description: requireText(entry.description, "Leistungsbezeichnung", 2000, false),
    priceCents: requireNonnegativeInteger(entry.priceCents, "Leistungspreis"),
  }));
  const serviceIds = new Set(services.map((entry) => entry.id));
  if (serviceIds.size !== services.length) throw new Error("Das Backup enthält doppelte Leistungs-IDs.");
  const invoices = requireArray(payload.invoices, "Rechnungen").map((entry, index) => {
    const id = requireId(entry?.id, `Rechnung ${index + 1}`);
    if (!/^\d{4}-\d{2}-\d{2}$/.test(entry.invoiceDate || "")) throw new Error("Ungültiges Rechnungsdatum im Backup.");
    const items = requireArray(entry.items, "Rechnungspositionen", 1000).map((item) => {
      const quantity = requirePositiveInteger(item.quantity, "Menge");
      const unitPriceCents = requireNonnegativeInteger(item.unitPriceCents, "Einzelpreis");
      return {
        serviceId: item.serviceId == null ? null : requireId(item.serviceId, "Leistungsreferenz"),
        description: requireText(item.description, "Position", 5000, false),
        quantity,
        unitPriceCents,
        totalCents: quantity * unitPriceCents,
      };
    });
    if (!items.length) throw new Error("Eine Rechnung im Backup enthält keine Position.");
    const totals = calculateTotals(items, requireNonnegativeInteger(entry.taxRate, "Steuersatz", 100));
    return {
      id,
      number: requireText(entry.number, "Rechnungsnummer", 200, false),
      invoiceDate: entry.invoiceDate,
      customerId: requireId(entry.customerId, "Kundenreferenz"),
      customerName: requireText(entry.customerName, "Rechnungskunde", 500, false),
      customerAddress: requireText(entry.customerAddress, "Rechnungsanschrift", 2000, false),
      customerPhone: requireText(entry.customerPhone || "", "Telefon", 100),
      customerDogs: requireText(entry.customerDogs || "", "Hundename", 500),
      items,
      taxRate: entry.taxRate,
      ...totals,
      createdAt: requireText(entry.createdAt || "", "Erstellzeit", 100),
      updatedAt: requireText(entry.updatedAt || "", "Änderungszeit", 100),
    };
  });
  const invoiceIds = new Set(invoices.map((entry) => entry.id));
  if (invoiceIds.size !== invoices.length) throw new Error("Das Backup enthält doppelte Rechnungs-IDs.");
  if (invoices.some((entry) => !customerIds.has(entry.customerId))) throw new Error("Eine Rechnung verweist auf einen fehlenden Kunden.");
  const settings = validateSettings(payload.settings || {});
  return { customers, services, invoices, settings };
}

function requireNonnegativeInteger(value, name, maximum = Number.MAX_SAFE_INTEGER) {
  if (!Number.isSafeInteger(value) || value < 0 || value > maximum) throw new Error(`Ungültiger Zahlenwert: ${name}.`);
  return value;
}

function requirePositiveInteger(value, name) {
  if (!Number.isSafeInteger(value) || value <= 0) throw new Error(`Ungültiger Zahlenwert: ${name}.`);
  return value;
}

function validateSettings(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error("Ungültige Einstellungen im Backup.");
  const settings = { ...DEFAULT_SETTINGS };
  for (const key of Object.keys(DEFAULT_SETTINGS)) {
    if (!(key in value)) continue;
    if (key === "nextInvoiceNumber") settings[key] = requirePositiveInteger(value[key], "nächste Rechnungsnummer");
    else if (key === "taxRate") settings[key] = requireNonnegativeInteger(value[key], "Steuersatz", 100);
    else settings[key] = requireText(value[key], key, key === "companyLogo" ? 10 * 1024 * 1024 : 10000);
  }
  if (settings.companyLogo && !/^data:image\/(png|jpeg|webp);base64,/i.test(settings.companyLogo)) {
    throw new Error("Das Logo im Backup hat ein nicht erlaubtes Format.");
  }
  return settings;
}

function replaceDatabase(payload) {
  return new Promise((resolve, reject) => {
    const names = ["customers", "services", "invoices", "settings"];
    const transaction = state.db.transaction(names, "readwrite");
    names.forEach((name) => transaction.objectStore(name).clear());
    payload.customers.forEach((entry) => transaction.objectStore("customers").put(entry));
    payload.services.forEach((entry) => transaction.objectStore("services").put(entry));
    payload.invoices.forEach((entry) => transaction.objectStore("invoices").put(entry));
    transaction.objectStore("settings").put({ key: "settings", value: payload.settings });
    transaction.oncomplete = () => resolve();
    transaction.onerror = () => reject(transaction.error);
    transaction.onabort = () => reject(transaction.error || new Error("Wiederherstellung wurde abgebrochen."));
  });
}

function updateConnectionStatus() {
  const status = document.querySelector("#connectionStatus");
  status.textContent = navigator.onLine ? "Lokal gespeichert" : "Offline bereit";
  status.classList.toggle("offline", !navigator.onLine);
}

function attachEvents() {
  document.querySelectorAll(".tab").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelectorAll(".tab, .view").forEach((node) => node.classList.remove("active"));
      button.classList.add("active");
      document.querySelector(`#${button.dataset.view}`).classList.add("active");
    });
  });
  document.querySelector("#newCustomer").addEventListener("click", () => openCustomerDialog());
  document.querySelector("#newService").addEventListener("click", () => openServiceDialog());
  document.querySelector("#newInvoice").addEventListener("click", () => openInvoiceDialog());
  document.querySelector("#addInvoiceItem").addEventListener("click", () => addInvoiceItem());
  document.querySelector("#customerSearch").addEventListener("input", renderCustomers);
  document.querySelector("#invoiceSearch").addEventListener("input", renderInvoices);
  document.querySelector("#customerForm").addEventListener("submit", saveCustomer);
  document.querySelector("#serviceForm").addEventListener("submit", saveService);
  document.querySelector("#invoiceForm").addEventListener("submit", saveInvoice);
  const customerSearch = document.querySelector("#invoiceForm [name=customerSearch]");
  if (customerSearch) {
    customerSearch.addEventListener("input", () => {
      document.querySelector("#invoiceForm [name=customerId]").value = "";
    });
    customerSearch.addEventListener("change", resolveCustomerInput);
  }
  document.querySelector("#settingsForm").addEventListener("submit", handleSettings);
  document.querySelector("#exportData").addEventListener("click", exportBackup);
  document.querySelector("#chooseImport").addEventListener("click", () => document.querySelector("#importData").click());
  document.querySelector("#importData").addEventListener("change", async (event) => {
    const file = event.currentTarget.files?.[0];
    if (!file) return;
    try {
      await importBackup(file);
    } catch (error) {
      alert(`Backup konnte nicht importiert werden: ${error.message}`);
    } finally {
      event.currentTarget.value = "";
    }
  });
  document.querySelectorAll("[data-close]").forEach((button) => {
    button.addEventListener("click", () => closeDialog(button.closest("dialog")));
  });
  document.body.addEventListener("click", async (event) => {
    const target = event.target;
    if (!(target instanceof HTMLElement)) return;
    const customerId = target.dataset.editCustomer;
    const serviceId = target.dataset.editService;
    const invoiceId = target.dataset.editInvoice;
    if (target.dataset.customerInvoice) {
      openInvoiceDialog({}, target.dataset.customerInvoice);
    } else if (customerId) {
      openCustomerDialog(state.customers.find((customer) => String(customer.id) === customerId));
    } else if (serviceId) {
      openServiceDialog(state.services.find((service) => String(service.id) === serviceId));
    } else if (invoiceId) {
      openInvoiceDialog(state.invoices.find((invoice) => String(invoice.id) === invoiceId));
    } else if (target.dataset.printInvoice) {
      const invoice = state.invoices.find((entry) => String(entry.id) === target.dataset.printInvoice);
      renderInvoicePrint(invoice);
      window.print();
    } else if (target.dataset.deleteCustomer && state.invoices.some((entry) => String(entry.customerId) === target.dataset.deleteCustomer)) {
      alert("Dieser Kunde kann nicht gelöscht werden, solange Rechnungen für ihn gespeichert sind.");
    } else if (target.dataset.deleteCustomer && confirm("Kunde wirklich löschen?")) {
      await remove("customers", target.dataset.deleteCustomer);
      await loadState();
      renderAll();
    } else if (target.dataset.deleteService && confirm("Leistung wirklich loeschen?")) {
      await remove("services", target.dataset.deleteService);
      await loadState();
      renderAll();
    } else if (target.dataset.deleteInvoice && confirm("Rechnung wirklich loeschen?")) {
      await remove("invoices", target.dataset.deleteInvoice);
      await loadState();
      renderAll();
    }
  });
}

async function main() {
  state.db = await openDb();
  attachEvents();
  updateConnectionStatus();
  window.addEventListener("online", updateConnectionStatus);
  window.addEventListener("offline", updateConnectionStatus);
  if (navigator.storage?.persist) await navigator.storage.persist();
  if ("serviceWorker" in navigator) {
    try {
      await navigator.serviceWorker.register("./sw.js", { scope: "./" });
    } catch (error) {
      console.error("Offline-Installation fehlgeschlagen", error);
    }
  }
  await loadState();
  renderAll();
}

main().catch((error) => {
  console.error(error);
  alert(`App konnte nicht gestartet werden: ${error.message}`);
});
