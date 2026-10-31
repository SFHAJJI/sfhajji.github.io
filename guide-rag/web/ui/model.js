// The "Modèle (optionnel)" panel: an OpenAI-compatible endpoint, key and model kept in
// sessionStorage only (this tab, this session), used by engine/llm.js when set.

import { LLMClient, LLMConfig, NotConfigured } from "../engine/llm.js";

const KEYS = { base_url: "guide_rag_llm_base_url", key: "guide_rag_llm_key", model: "guide_rag_llm_model" };

export class ModelPanel {
  constructor(root) {
    this.root = root;
    this.form = root.querySelector("#model-form");
    this.base_url = root.querySelector("#model-base-url");
    this.key = root.querySelector("#model-key");
    this.model = root.querySelector("#model-name");
    this.status = root.querySelector("#model-status");
    this.storage = safe_storage();
    this.form.addEventListener("submit", (e) => {
      e.preventDefault();
      this.save();
    });
    root.querySelector("#model-forget").addEventListener("click", () => this.forget());
    this.load();
  }

  load() {
    if (!this.storage) {
      this.status.textContent = "sessionStorage indisponible : le modèle ne peut pas être configuré ici.";
      return;
    }
    this.base_url.value = this.storage.getItem(KEYS.base_url) || "";
    this.key.value = this.storage.getItem(KEYS.key) || "";
    this.model.value = this.storage.getItem(KEYS.model) || "";
    this.show_status();
  }

  save() {
    if (!this.storage) return;
    this.storage.setItem(KEYS.base_url, this.base_url.value.trim());
    this.storage.setItem(KEYS.key, this.key.value.trim());
    this.storage.setItem(KEYS.model, this.model.value.trim());
    this.show_status();
  }

  forget() {
    if (this.storage) for (const k of Object.values(KEYS)) this.storage.removeItem(k);
    this.base_url.value = "";
    this.key.value = "";
    this.model.value = "";
    this.show_status();
  }

  show_status() {
    const client = this.client();
    this.status.textContent = client ? `Modèle configuré pour cette session : ${client.config.model} via ${client.config.base_url}.` : "Aucun modèle : le chemin déterministe tourne seul (model_used = « no model »).";
  }

  /** The client when a key is set, else null (the deterministic path). */
  client() {
    if (!this.storage) return null;
    try {
      return new LLMClient(LLMConfig.from_session(this.storage));
    } catch (e) {
      if (e instanceof NotConfigured) return null;
      throw e;
    }
  }
}

function safe_storage() {
  try {
    const s = window.sessionStorage;
    s.setItem("guide_rag_probe", "1");
    s.removeItem("guide_rag_probe");
    return s;
  } catch (e) {
    return null;
  }
}
