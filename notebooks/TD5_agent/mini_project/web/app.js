/* PIM Copilot — Vue 3 single-page chat UI (no build step; uses the vendored global build).
   Talks to the FastAPI backend's POST /chat, which runs the agent's reason -> act -> observe
   loop over the TD4 stdio server and returns the reply plus the tool-call trace.

   Human-in-the-loop: before the agent actually calls create_product, the backend PAUSES and
   /chat comes back with status "pending_confirmation" + a draft instead of a final reply.
   The UI renders that draft as a review card with Confirm / Reject buttons; POST /confirm
   resolves it and resumes the loop -- nothing is written to the catalog until the manager
   clicks Confirm. */
const { createApp, ref, computed, nextTick } = Vue;

const api = async (url, opts) => {
  const res = await fetch(url, opts);
  if (!res.ok) {
    let detail = res.statusText;
    try { detail = (await res.json()).detail || detail; } catch (e) {}
    throw new Error(detail);
  }
  return res.json();
};

const SUGGESTIONS = [
  {
    label: "Ask the catalog",
    text: "What noise-cancelling headphones do we carry under €300?",
  },
  {
    label: "Add a supplier product",
    text: "Add this new supplier product to our catalog, following your add_product skill. " +
      "When done, report the SKU you created and a one-line summary.\n\n" +
      "Supplier blurb:\nThe Aurora X. Our new flagship over-ear cans, active noise cancelling, " +
      "40 hours on a single charge, USB-C fast charge (10 min = a full day), Bluetooth 5.3, " +
      "fold flat for travel. Comes in midnight black and sand. Wholesale is €149, suggested " +
      "retail €249. 12-month warranty, MOQ is 50 units, ships from our Lyon warehouse from week 28.",
  },
];

createApp({
  setup() {
    // message shape: {role: 'user'|'assistant', text, trace?, pending?, confirming?}
    const messages = ref([]);
    const input = ref("");
    const sending = ref(false);
    const banner = ref("");
    const threadEl = ref(null);
    const inputEl = ref(null);

    const hasPending = computed(() => messages.value.some((m) => m.pending));

    const scrollDown = async () => {
      await nextTick();
      if (threadEl.value) threadEl.value.scrollTop = threadEl.value.scrollHeight;
    };

    const applyResult = (m, data) => {
      m.trace.push(...(data.trace || []));
      m.pending = data.status === "pending_confirmation" ? data.draft : null;
      if (data.status === "done") m.text = data.reply;
      if (data.status === "error") m.error = data.reply;
    };

    const send = async (text) => {
      const message = (text ?? input.value).trim();
      if (!message || sending.value || hasPending.value) return;
      banner.value = "";
      messages.value.push({ role: "user", text: message });
      input.value = "";
      sending.value = true;
      scrollDown();
      try {
        const data = await api("/chat", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ message }),
        });
        const m = { role: "assistant", text: "", trace: [], pending: null };
        applyResult(m, data);
        messages.value.push(m);
      } catch (e) {
        banner.value = "The copilot couldn't reply: " + e.message;
      } finally {
        sending.value = false;
        scrollDown();
      }
    };

    const resolvePending = async (m, approve) => {
      if (m.confirming) return;
      m.confirming = true;
      try {
        const data = await api("/confirm", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ approve }),
        });
        applyResult(m, data);
      } catch (e) {
        banner.value = "Couldn't resolve the draft: " + e.message;
      } finally {
        m.confirming = false;
        scrollDown();
      }
    };

    const reset = async () => {
      try { await api("/reset", { method: "POST" }); } catch (e) {}
      messages.value = [];
      banner.value = "";
    };

    const useSuggestion = (text) => {
      input.value = text;
      nextTick(() => inputEl.value && inputEl.value.focus());
    };

    const onKeydown = (e) => {
      if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        send();
      }
    };

    const argsPreview = (input_) => {
      const s = JSON.stringify(input_ ?? {});
      return s.length > 64 ? s.slice(0, 64) + "…" : s;
    };

    // {a: 1, b: null} -> [["a","1"],["b","null"]], for the draft card's key/value rows
    const entriesOf = (obj) =>
      Object.entries(obj || {}).map(([k, v]) => [k, v === null ? "null" : String(v)]);

    return {
      messages, input, sending, banner, threadEl, inputEl, hasPending,
      SUGGESTIONS, send, resolvePending, reset, useSuggestion, onKeydown, argsPreview, entriesOf,
    };
  },
  template: `
    <div class="topbar">
      <div class="mark"></div>
      <h1>PIM Copilot</h1>
      <span class="sub">your Claude Desktop, for the PIM</span>
      <div class="spacer"></div>
      <button class="ghost" @click="reset">New conversation</button>
      <a class="ghost-link" href="http://localhost:8000" target="_blank" rel="noopener">Open Light PIM ↗</a>
    </div>

    <div class="banner" v-if="banner">{{ banner }}</div>

    <div class="thread" ref="threadEl">
      <div class="empty-state" v-if="!messages.length">
        <div class="mark-lg"></div>
        <h2>Ask about the catalog, or add a product</h2>
        <p>Paste a messy supplier blurb — the agent categorizes it, fills every attribute, and
           <strong>drafts</strong> the entry for your review before anything is written.</p>
        <div class="suggestions">
          <button class="suggestion-chip" v-for="s in SUGGESTIONS" :key="s.label"
                  @click="useSuggestion(s.text)">
            <strong>{{ s.label }}</strong><br>{{ s.text.length > 90 ? s.text.slice(0, 90) + '…' : s.text }}
          </button>
        </div>
      </div>

      <div class="msg" :class="m.role" v-for="(m, i) in messages" :key="i">
        <div class="role">{{ m.role === 'user' ? 'You' : 'Copilot' }}</div>

        <div class="trace" v-if="m.trace && m.trace.length">
          <details class="trace-step" v-for="(t, j) in m.trace" :key="j" :open="t.tool === 'create_product'">
            <summary>
              <span class="arrow">→</span>
              <span class="tool-name">{{ t.tool }}</span>
              <span class="args">({{ argsPreview(t.input) }})</span>
              <span class="confirmed-tag" v-if="t.confirmed === true">confirmed</span>
              <span class="rejected-tag" v-if="t.confirmed === false">rejected</span>
              <span class="chev">▾</span>
            </summary>
            <div class="output">{{ t.output }}</div>
          </details>
        </div>

        <div class="confirm-card" v-if="m.pending">
          <div class="confirm-head">
            <span class="confirm-badge">Draft — awaiting your confirmation</span>
          </div>
          <div class="confirm-body">
            <div class="confirm-row"><span class="k">Name</span><span class="v">{{ m.pending.name }} <span class="ink-3">({{ m.pending.brand }})</span></span></div>
            <div class="confirm-row"><span class="k">Category</span><span class="v">{{ m.pending.category }}</span></div>
            <div class="confirm-row"><span class="k">Price</span><span class="v">€{{ m.pending.price }}</span></div>
            <div class="confirm-row"><span class="k">Short</span><span class="v">{{ m.pending.short_description }}</span></div>
            <div class="confirm-row"><span class="k">Long</span><span class="v">{{ m.pending.long_description }}</span></div>
            <div class="confirm-row">
              <span class="k">Attributes</span>
              <span class="v kv-list">
                <span class="kv" v-for="[k, val] in entriesOf(m.pending.attributes)" :key="k">
                  <span class="kv-k">{{ k }}</span>=<span class="kv-v" :class="{ null: val === 'null' }">{{ val }}</span>
                </span>
              </span>
            </div>
            <div class="confirm-row" v-if="entriesOf(m.pending.extra).length">
              <span class="k">Extra</span>
              <span class="v kv-list">
                <span class="kv" v-for="[k, val] in entriesOf(m.pending.extra)" :key="k">
                  <span class="kv-k">{{ k }}</span>=<span class="kv-v">{{ val }}</span>
                </span>
              </span>
            </div>
          </div>
          <div class="confirm-actions">
            <button class="confirm-btn reject" :disabled="m.confirming" @click="resolvePending(m, false)">✕ Reject</button>
            <button class="confirm-btn approve" :disabled="m.confirming" @click="resolvePending(m, true)">✓ Confirm &amp; create</button>
          </div>
        </div>

        <div class="bubble" v-if="m.text">{{ m.text }}</div>
        <div class="bubble error" v-if="m.error">{{ m.error }}</div>
      </div>

      <div class="msg assistant" v-if="sending">
        <div class="role">Copilot</div>
        <div class="bubble"><div class="thinking"><span class="dot"></span><span class="dot"></span><span class="dot"></span></div></div>
      </div>
    </div>

    <div class="composer">
      <textarea ref="inputEl" v-model="input" @keydown="onKeydown" :disabled="sending || hasPending"
                :placeholder="hasPending ? 'Resolve the pending draft above first…' : 'Ask about the catalog, or paste a supplier blurb…'"
                rows="1"></textarea>
      <button class="send" @click="send()" :disabled="sending || hasPending || !input.trim()">Send</button>
    </div>
    <div class="hint">Enter to send · Shift+Enter for a new line</div>
  `,
}).mount("#app");
