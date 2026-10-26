/* 群日报工作台 · 前端
 *
 * 无构建链。Vue 3 从本地 vendor 加载，模板是字符串。
 * 数据只从 /api/browse · /api/search · /api/messages 拿，不直连 SQLite。
 *
 * 采集和日报状态分别显示；所有表面共享读取契约和状态文案。
 */
(function () {
  "use strict";

  const { createApp, reactive, computed, watch, nextTick } = Vue;

  // ────────────────────────────────────────────── 常量

  // collection/report remain independent facts; state below is only a display summary.
  const STATE_META = {
    ready: { label: "可读", cls: "ready", title: "日报可读", note: "日报产物可打开。" },
    stale: { label: "旧稿待更新", cls: "pending", title: "旧稿可读，等待更新", note: "素材已变化，下面保留上次日报。请在 WorkBuddy 中核对后更新。" },
    pending: { label: "待产稿", cls: "pending", title: "已采集，等待产稿", note: "已有素材，尚未生成日报；素材是否足够以产稿结果为准。" },
    insufficient: { label: "素材不足", cls: "empty", title: "素材不足，未成篇", note: "本次素材不足以成篇。可在 WorkBuddy 中核对来源或选择其他日期。" },
    orphan: { label: "素材归档缺失", cls: "orphan", title: "日报保留，素材归档缺失", note: "可查看已有日报；原始素材暂时无法核对，请在 WorkBuddy 中恢复归档。" },
    empty: { label: "成功零消息", cls: "empty", title: "采集完成，该日零消息", note: "已成功完成目标范围的采集，结果为零消息。" },
    not_collected: { label: "未采集", cls: "missing", title: "这一天尚未采集", note: "尚无采集结果，不能据此判断群内是否有消息。" },
    collection_running: { label: "采集中", cls: "pending", title: "正在采集素材", note: "采集尚在进行，结果未确认。" },
    report_running: { label: "产稿中", cls: "pending", title: "日报正在生成", note: "产稿尚在进行，已有稿件可继续阅读。" },
    collection_failed: { label: "采集失败", cls: "orphan", title: "本次采集失败", note: "本次采集未成功完成。请将群与日期交给 WorkBuddy，核对覆盖缺口后重试。" },
    report_failed: { label: "产稿失败", cls: "orphan", title: "本次产稿失败", note: "请在 WorkBuddy 中核对产稿步骤后重试；已有稿件仍保留。" },
  };
  const FALLBACK_STATE = { label: "未核验", cls: "missing", title: "状态未核验", note: "服务未提供可核验的状态，请重新检查或在 WorkBuddy 中核对。" };
  const COLLECTION_META = {
    not_collected: "not_collected", running: "collection_running", collected: "collected",
    empty: "empty", failed: "collection_failed",
  };
  const REPORT_META = {
    pending: "pending", running: "report_running", ready: "ready", stale: "stale",
    insufficient: "insufficient", failed: "report_failed", orphan: "orphan",
  };
  STATE_META.collected = { label: "采集成功", cls: "ready", title: "采集成功", note: "" };

  function artifactURL(value) {
    if (typeof value !== "string" || !value.startsWith("/r/")) return null;
    try {
      const url = new URL(value, location.origin);
      if (url.origin !== location.origin || !url.pathname.startsWith("/r/") || url.search || url.hash) return null;
      if (value.includes("\\") || /(?:^|\/)\.{1,2}(?:\/|$)/.test(decodeURIComponent(value))) return null;
      return url.pathname;
    } catch (_) { return null; }
  }

  function prepareEntry(entry) {
    const c = entry.collection || {};
    const r = entry.report || {};
    const html = artifactURL(r.html_url), png = artifactURL(r.png_url);
    let collectionState = Object.hasOwn(COLLECTION_META, c.state) ? COLLECTION_META[c.state] : "unknown";
    if (["collected", "empty"].includes(collectionState) && c.coverage?.complete !== true) collectionState = "unknown";
    if (collectionState === "empty" && c.message_count !== 0) collectionState = "unknown";
    if (collectionState === "collected" && (!Number.isInteger(c.message_count) || c.message_count <= 0)) collectionState = "unknown";
    let reportState = Object.hasOwn(REPORT_META, r.state) ? REPORT_META[r.state] : "unknown";
    if (["ready", "stale", "orphan"].includes(reportState) && !html && !png) reportState = "unknown";
    let state = reportState;
    if (["not_collected", "collection_running", "collection_failed", "empty", "unknown"].includes(collectionState)
        && !["ready", "stale", "orphan", "report_failed", "report_running"].includes(reportState)) state = collectionState;
    return { ...entry, state, collectionState, reportState, html_url: html, png_url: png,
      total: Number.isInteger(c.message_count) && c.message_count >= 0 ? c.message_count : null,
      unique_senders: c.message_count == null ? null : entry.unique_senders,
      chars: c.message_count == null ? null : entry.chars,
      composed_at: r.composed_at || null };
  }

  function summarize(entries) {
    const counts = {};
    entries.forEach(e => { counts[e.state] = (counts[e.state] || 0) + 1; });
    return { counts, expected: entries.length,
      archived: entries.filter(e => ["collected", "empty"].includes(e.collectionState)).length,
      readable: entries.filter(e => e.html_url || e.png_url).length };
  }

  // The HTTP boundary adapts contract fields once, shared by every reading view.
  function prepareResponse(path, body) {
    const entries = rows => (rows || []).map(prepareEntry);
    if (path === "/api/entry") return prepareEntry(body);
    if (path === "/api/day") return { ...body, chats: entries(body.chats) };
    if (path === "/api/chat") return { ...body, entries: entries(body.entries) };
    if (path !== "/api/browse") return body;
    return { ...body,
      recent: (body.recent || []).map(g => ({ ...g, entries: entries(g.entries) })),
      today: body.today ? { ...body.today, chats: entries(body.today.chats) } : null,
      matrix: body.matrix ? { ...body.matrix, rows: (body.matrix.rows || []).map(r => ({ ...r, cells: entries(r.cells) })) } : null,
    };
  }

  // ────────────────────────────────────────────── 工具

  function parseISO(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3]);
  }

  function dayDiff(later, earlier) {
    const a = parseISO(later), b = parseISO(earlier);
    if (!a || !b) return 0;
    return Math.round((a - b) / 86400000);
  }

  const WEEK = "一二三四五六日";

  function weekday(s) {
    const d = parseISO(s);
    return d ? "周" + WEEK[(d.getDay() + 6) % 7] : "";
  }

  function agoText(s) {
    const d = parseISO(s);
    if (!d) return "";
    const now = new Date();
    const today = new Date(now.getFullYear(), now.getMonth(), now.getDate());
    const n = Math.round((today - d) / 86400000);
    if (n === 0) return "今天";
    if (n === 1) return "昨天";
    if (n === 2) return "前天";
    return `${n} 天前`;
  }

  function md(s) {
    return (s || "").slice(5);
  }

  function hm(s) {
    // "2026-10-26 09:48:10" → "09:48"
    const m = /(\d{2}):(\d{2})/.exec((s || "").slice(11));
    return m ? `${m[1]}:${m[2]}` : "";
  }

  function num(n) {
    return n == null ? "—" : Number(n).toLocaleString("zh-CN");
  }

  function escapeHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;")
      .replace(/'/g, "&#39;");
  }

  function highlight(text, q) {
    const safe = escapeHtml(text);
    if (!q) return safe;
    const needle = escapeHtml(q);
    if (!needle) return safe;
    const re = new RegExp(
      "(" + needle.replace(/[.*+?^${}()|[\]\\]/g, "\\$&") + ")",
      "gi"
    );
    return safe.replace(re, "<mark>$1</mark>");
  }

  function meta(state) {
    return Object.hasOwn(STATE_META, state) ? STATE_META[state] : FALLBACK_STATE;
  }

  function chatURL(username) {
    return "/c/" + encodeURIComponent(username);
  }

  function detailURL(username, date) {
    return "/c/" + encodeURIComponent(username) + "/" + date;
  }

  async function getJSON(url) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), 15000);
    let r;
    try {
      r = await fetch(url, {
        headers: { Accept: "application/json" },
        signal: controller.signal,
      });
    } catch (e) {
      clearTimeout(timer);
      if (e && e.name === "AbortError") {
        throw new Error("本机服务响应超时，请确认采集或索引没有卡住");
      }
      throw new Error("连不上本机服务，请在 WorkBuddy 中重新启动群日报阅读服务，再重新检查");
    }

    let body = null;
    try {
      body = await r.json();
    } catch (e) {
      throw new Error(e?.name === "AbortError" ? "本机服务响应超时，请重新检查。" : `响应不是 JSON（HTTP ${r.status}）`);
    } finally {
      clearTimeout(timer);
    }
    if (!r.ok) {
      throw new Error((body && body.error) || `HTTP ${r.status}`);
    }
    return prepareResponse(new URL(url, location.origin).pathname, body);
  }

  async function copyText(text) {
    let timer;
    try {
      await Promise.race([
        navigator.clipboard.writeText(text),
        new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("clipboard unconfirmed")), 1500); }),
      ]);
    } finally { clearTimeout(timer); }
  }

  // ────────────────────────────────────────────── 路由

  function parseRoute(url) {
    const u = new URL(url, location.origin);
    const p = u.pathname;
    const seg = p.split("/").filter(Boolean);

    if (p === "/" || p === "") return { name: "recent", key: "recent" };
    if (p === "/dates") return { name: "dates", key: "dates" };
    if (p === "/chats") return { name: "chats", key: "chats" };
    if (p === "/matrix") return { name: "matrix", key: "matrix" };
    if (p === "/search")
      return { name: "search", key: "search", filters: {
        q: u.searchParams.get("q") || "", chat: u.searchParams.get("chat") || "",
        from: u.searchParams.get("from") || "", to: u.searchParams.get("to") || "",
      } };

    if (seg[0] === "d" && seg[1]) return { name: "day", key: "dates", date: seg[1] };

    if (seg[0] === "c" && seg[1] && seg[2]) {
      return {
        name: "detail",
        key: "chats",
        username: decodeURIComponent(seg[1]),
        date: seg[2],
      };
    }
    if (seg[0] === "c" && seg[1]) {
      return { name: "chat", key: "chats", username: decodeURIComponent(seg[1]) };
    }
    return { name: "notfound", key: "" };
  }

  // ────────────────────────────────────────────── 共享小组件

  const Badge = {
    props: { state: { type: String, required: true } },
    computed: {
      m() {
        return meta(this.state);
      },
    },
    template: `<span class="badge" :class="'s-' + m.cls">{{ m.label }}</span>`,
  };

  const EntryStatus = {
    props: ["entry"], components: { Badge },
    template: `<span class="entry-status"><span>采集 <Badge :state="entry.collectionState || 'unknown'" /></span><span>日报 <Badge :state="entry.reportState || 'unknown'" /></span></span>`,
  };

  const WorkBuddyAction = {
    props: ["username", "date"],
    setup(props) {
      const state = reactive({ notice: "" });
      const request = computed(() => props.username
        ? "请使用微信群日报 Skill，核对群 ID " + JSON.stringify(props.username) + " 在 " + (props.date || "所选日期") + " 的采集和日报状态，保留已有日报；如需补跑，请先列出缺口并让我确认范围。"
        : "请使用微信群日报 Skill，核对本机关注群、首份日报与定时任务状态，列出缺口和下一步；如需补跑，请先让我确认群与日期范围。");
      async function copy() {
        try { await copyText(request.value); state.notice = "已复制，请粘贴到 WorkBuddy。"; }
        catch (_) { state.notice = "复制未成功，请手动复制上方指令。"; }
      }
      return { state, request, copy };
    },
    template: `<details class="workbuddy-action"><summary>在 WorkBuddy 中处理</summary><p class="setup-request">{{ request }}</p><button type="button" class="btn quiet" @click="copy">复制处理指令</button><span class="copy-notice" role="status">{{ state.notice }}</span></details>`,
  };

  const Dot = {
    // state 允许为空：日期轴上有「不知道」的情况（聚合行缺失），
    // 那时候宁可不画点，也不要画一个假的「无归档」。
    props: { state: { type: String, default: "" } },
    computed: {
      m() {
        return this.state ? meta(this.state) : { cls: "none" };
      },
    },
    template: `<span class="dot" :class="'d-' + m.cls" aria-hidden="true"></span>`,
  };

  const EmptyBox = {
    props: { title: String, body: String },
    template: `
      <div class="emptybox">
        <b v-if="title">{{ title }}</b>
        <span v-if="body">{{ body }}</span>
        <slot />
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：最近流

  const RecentView = {
    props: ["data", "days"],
    emits: ["nav-rows"],
    components: { Badge, EntryStatus, Dot, EmptyBox, WorkBuddyAction },
    setup(props, { emit }) {
      const groups = computed(() => {
        const d = props.data;
        if (!d || !d.recent) return [];
        const limit = props.days;
        const slice = d.recent.slice(0, limit);
        return slice.map(g => ({ ...g, byState: summarize(g.entries || []).counts,
          expected: (g.entries || []).length }));
      });

      // 键盘导航：每个群卡片一个落点，外加日期组头
      watch(
        groups,
        (gs) => {
          const rows = [];
          gs.forEach((g) => {
            g.entries.forEach((e) => {
              rows.push({
                href: detailURL(e.username, g.date),
                label: `${e.chat} ${md(g.date)}`,
              });
            });
          });
          emit("nav-rows", rows);
        },
        { immediate: true }
      );

      const today = computed(() => (props.data ? props.data.today : null));

      const todayLine = computed(() => {
        const t = today.value;
        if (!t) return null;
        const summary = summarize(t.chats || []);
        return { date: t.date, head: `可读 ${summary.readable} 份日报`, ready: summary.readable,
          bits: [`${summary.expected} 个群中 ${summary.archived} 个采集成功`],
          note: "采集与日报状态分别显示；定时运行以宿主回读为准。" };
      });

      const dateTitle = (ds) => {
        const a = agoText(ds);
        return a && a !== ds ? a : ds;
      };

      return { groups, todayLine, dateTitle, md, num, weekday, detailURL, meta };
    },
    template: `
      <div>
        <div class="hd">
          <div>
            <h1>最近日报</h1>
            <div class="sub" v-if="data">
              关注 <b>{{ (data.chats || []).filter(c => c.followed).length }}</b> 个群
              · 共 <b>{{ num(data.overview.reports) }}</b> 份日报
              · <b>{{ num(data.overview.msgs) }}</b> 条消息
              <template v-if="data.overview.last_date">
                · 最近归档 {{ data.overview.last_date }}（{{ dateTitle(data.overview.last_date) }}）
              </template>
            </div>
          </div>
          <div class="tabs">
            <a v-for="n in [3,7,14,30]" :key="n"
               :href="n === 7 ? '/' : '/?days=' + n"
               :class="{ on: n === days }"
               @click.prevent="$emit('pick-days', n)">{{ n }} 天</a>
          </div>
        </div>

        <!-- 日期及状态来自服务，不按浏览器时间推断运行是否成功。 -->
        <div class="todaybar" v-if="todayLine">
          <span class="tb-date">{{ todayLine.date }} {{ weekday(todayLine.date) }}</span>
          <span class="tb-main">
            {{ todayLine.head }}
          </span>
          <span class="tb-note">{{ todayLine.bits.join(' · ') }}</span>
          <span class="tb-drop"></span>
          <span class="tb-note" v-if="todayLine.note">{{ todayLine.note }}</span>
        </div>

        <EmptyBox v-if="!groups.length"
          title="还没有任何归档"
          body="请在 WorkBuddy 中调用微信群日报，选择需要采集的群与日期。" />

        <section class="daygroup" v-for="g in groups" :key="g.date">
          <div class="dhead">
            <a :href="'/d/' + g.date">
              <b>{{ g.date }}</b>
              <span class="wd">{{ weekday(g.date) }} · {{ dateTitle(g.date) }}</span>
            </a>
            <span class="st">
              可读 {{ (g.entries || []).filter(e => e.html_url || e.png_url).length }} / {{ g.expected }}
              <template v-if="g.byState.pending"> · 未生成 {{ g.byState.pending }}</template>
              <template v-if="g.byState.insufficient"> · 素材不足 {{ g.byState.insufficient }}</template>
              <template v-if="g.byState.orphan"> · 数据缺失 {{ g.byState.orphan }}</template>
              <template v-if="g.byState.not_collected"> · 未采集 {{ g.byState.not_collected }}</template>
              · {{ num(g.total) }} 条
            </span>
          </div>

          <div class="grid2">
            <article class="mini" v-for="e in g.entries" :key="e.username"
                     :class="{ 'no-thumb': !e.png_url }">
              <a class="card-link" :href="'/c/' + encodeURIComponent(e.username) + '/' + g.date"
                 :aria-label="e.chat + ' ' + e.username + ' ' + g.date + ' ' + meta(e.state).label"></a>
              <div class="mthumb" v-if="e.png_url">
                <img :src="e.png_url" alt="" loading="lazy" />
              </div>
              <div class="mbody">
                <a class="mname" :href="'/c/' + encodeURIComponent(e.username)">{{ e.chat }}</a><span class="identity">{{ e.username }}</span>
                <div class="mttl" :class="{ quiet: !e.title }">
                  {{ e.title || meta(e.state).title }}
                </div>
                <div class="mmeta">
                  <span>{{ num(e.total) }} 条</span>
                  <template v-if="e.composed_at">· <span>{{ e.composed_at.slice(5, 16) }}</span></template>
                  <EntryStatus :entry="e" />
                </div>
              </div>
            </article>
          </div>

        </section>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：按日期

  const DatesView = {
    props: ["data"],
    emits: ["nav-rows"],
    components: { Dot, EmptyBox },
    setup(props, { emit }) {
      /** 展示服务返回的日期间隔，不推断采集失败或关注生效范围。 */
      const rows = computed(() => {
        const d = props.data;
        if (!d) return [];
        const days = d.days || [];

        // 计数走全量索引（dayrows），明细走 recent。
        // 反过来的话，超过 recent 窗口的老日子会算成「0 个群 · 0 条」，
        // 而它们明明有归档——轴的数字不能说谎。
        const agg = {};
        (d.dayrows || []).forEach((x) => {
          agg[x.date] = x;
        });
        const index = {};
        (d.recent || []).forEach((g) => {
          index[g.date] = g;
        });

        const out = [];
        for (let i = 0; i < days.length; i++) {
          const date = days[i];
          const a = agg[date];
          const entries = index[date] ? index[date].entries || [] : [];
          const summary = index[date] ? summarize(entries) : null;
          const ready = summary ? summary.readable : null;
          const pend = summary ? summary.counts.pending : null;
          const empty = summary ? summary.counts.insufficient : null;

          out.push({
            type: "day",
            date,
            chats: summary ? summary.archived : null,
            total: a ? a.total : 0,
            ready,
            pend,
            empty,
            // 没有聚合行时不要断言「无归档」，宁可留空——说错了比不说明更糟
            state: null,
          });

          const next = days[i + 1];
          if (next) {
            const gap = dayDiff(date, next) - 1;
            if (gap > 0) {
              out.push({
                type: "gap",
                from: next,
                to: date,
                missed: gap,
              });
            }
          }
        }
        return out;
      });

      watch(
        rows,
        (rs) => {
          emit(
            "nav-rows",
            rs
              .filter((r) => r.type === "day")
              .map((r) => ({ href: "/d/" + r.date, label: r.date }))
          );
        },
        { immediate: true }
      );

      return { rows, md, num, weekday };
    },
    template: `
      <div>
        <div class="hd">
          <div>
            <h1>按日期</h1>
            <div class="sub" v-if="data">
              <b>{{ (data.days || []).length }}</b> 天有归档
              · 覆盖 {{ data.overview.first_date }} → {{ data.overview.last_date }}
              · 虚线处表示没有日期记录
            </div>
          </div>
          <div class="tabs"><a href="/matrix">看矩阵 ›</a></div>
        </div>

        <EmptyBox v-if="!rows.length" title="还没有归档" body="请在 WorkBuddy 中核对关注群与需要采集的日期。" />

        <div class="list" v-else>
          <template v-for="(r, i) in rows" :key="i">
            <a v-if="r.type === 'day'" class="item" :href="'/d/' + r.date">
              <span class="d"><Dot :state="r.state" />{{ md(r.date) }}</span>
              <span class="t">
                {{ weekday(r.date) }}
                <span class="note"> · {{ num(r.chats) }} 个群采集成功 · {{ num(r.total) }} 条</span>
              </span>
              <span class="n">
                可读 {{ num(r.ready) }}
                <template v-if="r.pend"> · 待 {{ r.pend }}</template>
                <template v-if="r.empty"> · 素材不足 {{ r.empty }}</template>
              </span>
            </a>
            <div v-else class="gapbar">
              <span class="gap-line"></span>
              <span>{{ r.from }} → {{ r.to }} 之间有 {{ r.missed }} 天未返回记录</span>
              <span class="gap-line"></span>
            </div>
          </template>
        </div>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：当天

  const DayView = {
    props: ["data", "date"],
    emits: ["nav-rows"],
    components: { Badge, EntryStatus, EmptyBox, WorkBuddyAction },
    setup(props, { emit }) {
      const remote = reactive({ loading: false, error: null, data: null });
      let requestId = 0;

      async function loadDay() {
        const date = props.date;
        const my = ++requestId;
        remote.loading = true;
        remote.error = null;
        remote.data = null;
        try {
          const d = await getJSON("/api/day?date=" + encodeURIComponent(date));
          if (my === requestId) remote.data = d;
        } catch (e) {
          if (my === requestId) remote.error = e.message;
        } finally {
          if (my === requestId) remote.loading = false;
        }
      }

      const day = computed(() => {
        // 缓存只匹配当前日期；独立接口失败始终显示错误。
        const d = props.data;
        const cached = d && (d.recent || []).find((x) => x.date === props.date);
        const g = remote.data || cached;
        if (!g) return null;
        // g 有两个来源，而 `chats` 在两边的类型不一样：
        // browse 的 recent[] 里是数字（当天有几个群），/api/day 里是数组（群列表）。
        // 早期写成 `g.chats || g.entries`，走缓存分支时拿到数字 2，
        // 接着 2.map(...) 抛错、整页白屏。只认数组，不是数组就退回 entries。
        const entries = Array.isArray(g.chats) ? g.chats : g.entries || [];
        return { ...g, entries };
      });

      const nav = computed(() => {
        const days = (props.data && props.data.days) || [];
        const i = days.indexOf(props.date);
        return {
          newer: i > 0 ? days[i - 1] : null,
          older: i >= 0 && i < days.length - 1 ? days[i + 1] : null,
        };
      });

      const stats = computed(() => {
        const g = day.value;
        if (!g) return null;
        return { ...summarize(g.entries || []), total: g.total };
      });

      watch(
        day,
        (g) => {
          emit(
            "nav-rows",
            g
              ? (g.entries || []).map((e) => ({
                  href: detailURL(e.username, props.date),
                  label: e.chat,
                }))
              : []
          );
        },
        { immediate: true }
      );
      watch(() => props.date, loadDay, { immediate: true });

      return { day, nav, stats, remote, loadDay, meta, num, weekday, detailURL, chatURL, md };
    },
    template: `
      <div>
        <div class="banner" v-if="remote.loading && !day" aria-live="polite">正在读取这一天…</div>
        <div class="banner err" v-else-if="remote.error" role="alert">
          这一天取不到：{{ remote.error }}
          <button type="button" class="btn" @click="loadDay">重试</button>
        </div>
        <EmptyBox v-else-if="!day"
          title="这一天没有归档"
          body="可以从日期轴另选一天；如果这里本该有数据，请检查采集。" />

        <template v-else>
          <div class="hd">
            <div>
              <h1>{{ date }}</h1>
              <div class="sub" v-if="stats">
                {{ weekday(date) }}
                · {{ stats.archived }} 个群采集成功
                · <b>{{ num(stats.total) }}</b> 条
                · 可读 <b>{{ stats.readable }}</b> / {{ stats.expected }}
                <template v-if="stats.counts.pending"> · 未生成 {{ stats.counts.pending }}</template>
                <template v-if="stats.counts.insufficient"> · 素材不足 {{ stats.counts.insufficient }}</template>
                <template v-if="stats.counts.orphan"> · 数据缺失 {{ stats.counts.orphan }}</template>
                <template v-if="stats.counts.not_collected"> · 未采集 {{ stats.counts.not_collected }}</template>
              </div>
            </div>
            <div class="pager">
              <a v-if="nav.older" :href="'/d/' + nav.older">‹ {{ md(nav.older) }}（更早）</a>
              <a v-if="nav.newer" :href="'/d/' + nav.newer">{{ md(nav.newer) }}（更新）›</a>
            </div>
          </div>

          <article class="card" v-for="c in day.entries" :key="c.username"
                   :class="{ 'no-thumb': !c.png_url }">
            <a class="card-link" :href="detailURL(c.username, date)"
               :aria-label="c.chat + ' ' + c.username + ' ' + date"></a>
            <div class="thumb" v-if="c.png_url">
              <img :src="c.png_url" alt="" loading="lazy" />
            </div>
            <div class="body">
              <div class="rowline">
                <a class="name" :href="chatURL(c.username)">{{ c.chat }}</a><span class="identity">{{ c.username }}</span>
                <EntryStatus :entry="c" />
              </div>
              <div class="ttl" :class="{ nil: !c.title }">
                {{ c.title || meta(c.state).title }}
              </div>
              <div class="lead" v-if="c.lead">{{ c.lead }}</div>
              <div class="ft">
                <span>{{ num(c.total) }} 条 · {{ num(c.unique_senders) }} 人 · {{ num(c.chars) }} 字</span>
                <a :href="chatURL(c.username)">历史 ›</a>
                <a v-if="c.png_url" :href="c.png_url" target="_blank" rel="noopener">长图</a>
                <a v-if="c.html_url" :href="c.html_url" target="_blank" rel="noopener">日报</a>
              </div>
            </div>
          </article>

        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：按群

  const ChatsView = {
    props: ["data"],
    emits: ["nav-rows"],
    components: { Dot, EmptyBox },
    setup(props, { emit }) {
      const groups = computed(() => {
        const d = props.data;
        if (!d) return { followed: [], others: [] };
        const rows = d.chats || [];
        return {
          followed: rows.filter((r) => r.followed),
          others: rows.filter((r) => !r.followed),
        };
      });

      // 群级旧 last_state 不足以证明采集或日报成功。
      const stateOf = (r) => r.collection || r.report ? prepareEntry(r).state : "unknown";

      watch(
        groups,
        (g) => {
          emit(
            "nav-rows",
            [...g.followed, ...g.others].map((r) => ({
              href: chatURL(r.username),
              label: r.chat,
            }))
          );
        },
        { immediate: true }
      );

      return { groups, stateOf, num, md };
    },
    template: `
      <div>
        <div class="hd">
          <div>
            <h1>按群</h1>
            <div class="sub" v-if="data">
              关注 <b>{{ groups.followed.length }}</b> 个
              · 另有 <b>{{ groups.others.length }}</b> 个有归档但未关注
              · 在 WorkBuddy 对话中调整关注群
            </div>
          </div>
          <div class="tabs"><a href="/matrix">看矩阵 ›</a></div>
        </div>

        <EmptyBox v-if="!data || !(groups.followed.length || groups.others.length)"
          title="还没有归档，关注名单也是空的"
          body="请在 WorkBuddy 对话中选择关注群并生成首份日报。" />

        <template v-else>
          <div class="sec">关注 的 群</div>
          <div class="list" v-if="groups.followed.length">
            <a class="item" v-for="r in groups.followed" :key="r.username" :href="'/c/' + encodeURIComponent(r.username)">
              <span class="d"><Dot :state="stateOf(r)" />{{ r.last_date ? md(r.last_date) : '—' }}</span>
              <span class="t">{{ r.chat }}<span class="identity">{{ r.username }}</span>
                <span class="note"> · {{ r.days }} 天 · {{ num(r.total) }} 条<template v-if="r.last_report"> · 最近日报 {{ md(r.last_report) }}</template><template v-else-if="r.days"> · 还没出过日报</template></span>
              </span>
              <span class="n">{{ r.reports }} 份</span>
            </a>
          </div>
          <EmptyBox v-else title="还没有关注的群"
            body="请在 WorkBuddy 对话中选择关注群。" />

          <template v-if="groups.others.length">
            <div class="sec">其他 有归档 的 群</div>
            <div class="list">
              <a class="item" v-for="r in groups.others" :key="r.username" :href="'/c/' + encodeURIComponent(r.username)">
                <span class="d"><Dot :state="stateOf(r)" />{{ r.last_date ? md(r.last_date) : '—' }}</span>
                <span class="t">{{ r.chat }}
                  <span class="note"> · {{ r.days }} 天 · {{ num(r.total) }} 条<template v-if="r.last_report"> · 最近日报 {{ md(r.last_report) }}</template><template v-else> · 还没出过日报</template></span>
                </span>
                <span class="n">{{ r.reports }} 份</span>
              </a>
            </div>
          </template>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：群时间线

  const ChatView = {
    props: ["data", "username"],
    emits: ["nav-rows"],
    components: { Badge, EntryStatus, EmptyBox, WorkBuddyAction },
    setup(props, { emit }) {
      const remote = reactive({ loading: false, error: null, data: null });
      let requestId = 0;

      async function loadChat() {
        const username = props.username;
        const my = ++requestId;
        remote.loading = true;
        remote.error = null;
        remote.data = null;
        try {
          const d = await getJSON("/api/chat?username=" + encodeURIComponent(username) + "&limit=60");
          if (my === requestId) remote.data = d;
        } catch (e) {
          if (my === requestId) remote.error = e.message;
        } finally {
          if (my === requestId) remote.loading = false;
        }
      }

      const rows = computed(() => {
        if (remote.data) return remote.data.entries || [];
        const d = props.data;
        if (!d || !d.recent) return [];
        const all = [];
        d.recent.forEach((g) => {
          (g.entries || []).forEach((e) => {
            if (e.username === props.username) all.push(e);
          });
        });
        all.sort((a, b) => (a.date < b.date ? 1 : -1));
        return all;
      });

      const chat = computed(() => {
        if (remote.data) return remote.data;
        const d = props.data;
        if (!d) return null;
        const r = (d.chats || []).find((c) => c.username === props.username);
        if (r) return r;
        const first = rows.value[0];
        return first ? { chat: first.chat, username: props.username } : null;
      });

      const stats = computed(() => {
        const rs = rows.value;
        if (!rs.length) return null;
        const collected = rs.filter(r => ["collected", "empty"].includes(r.collectionState) && Number.isInteger(r.total));
        const totals = collected.map(r => r.total);
        const avg = totals.length
          ? Math.round(totals.reduce((a, b) => a + b, 0) / totals.length)
          : 0;
        return {
          days: collected.length,
          avg,
          ready: rs.filter((r) => r.html_url || r.png_url).length,
          first: rs[rs.length - 1].date,
          last: rs[0].date,
        };
      });

      watch(
        rows,
        (rs) => {
          emit(
            "nav-rows",
            rs.map((r) => ({ href: detailURL(props.username, r.date), label: r.date }))
          );
        },
        { immediate: true }
      );
      watch(() => props.username, loadChat, { immediate: true });

      return { rows, chat, stats, remote, loadChat, meta, num, md, weekday, detailURL };
    },
    template: `
      <div>
        <div class="banner" v-if="remote.loading && !chat" aria-live="polite">正在读取群时间线…</div>
        <div class="banner err" v-else-if="remote.error" role="alert">
          群时间线取不到：{{ remote.error }}
          <button type="button" class="btn" @click="loadChat">重试</button>
        </div>
        <EmptyBox v-else-if="!chat"
          title="没有这个群"
          body="该 username 没有任何归档记录，也不在关注名单里。" />

        <template v-else>
          <div class="hd">
            <div>
              <h1>{{ chat.chat }}</h1>
              <div class="sub" v-if="stats">
                归档 <b>{{ stats.days }}</b> 天
                · 平均 <b>{{ num(stats.avg) }}</b> 条/天
                · 已出 <b>{{ stats.ready }}</b> 份日报
                · {{ stats.first }} → {{ stats.last }}
              </div>
            </div>
            <div class="pager"><a href="/chats">按群</a></div>
          </div>

          <div class="crumb">
            <span class="sid">{{ username }}</span>
            —— 群改名后仍按此群 ID 回看
          </div>

          <div class="list">
            <a class="item" v-for="r in rows" :key="r.date" :href="detailURL(username, r.date)">
              <span class="d">{{ md(r.date) }}</span>
              <span class="t">{{ weekday(r.date) }}<span class="note" v-if="r.title"> · {{ r.title }}</span><span class="note" v-else> · {{ meta(r.state).title }}</span></span>
              <span class="n">{{ num(r.total) }}</span>
              <span class="n"><EntryStatus :entry="r" /></span>
            </a>
          </div>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：明细

  const DetailView = {
    props: ["data", "username", "date"],
    emits: ["nav-rows"],
    components: { Badge, EntryStatus, EmptyBox, WorkBuddyAction },
    setup(props, { emit }) {
      const remote = reactive({ loading: false, error: null, data: null });
      let entryReq = 0;

      async function loadEntry() {
        const key = props.username + "@" + props.date;
        const my = ++entryReq;
        remote.loading = true;
        remote.error = null;
        remote.data = null;
        try {
          const d = await getJSON(
            `/api/entry?date=${encodeURIComponent(props.date)}` +
              `&username=${encodeURIComponent(props.username)}`
          );
          if (my === entryReq && key === props.username + "@" + props.date) {
            remote.data = d;
          }
        } catch (e) {
          if (my === entryReq) remote.error = e.message;
        } finally {
          if (my === entryReq) remote.loading = false;
        }
      }

      const entry = computed(() => {
        if (remote.data) return remote.data;
        const d = props.data;
        if (!d) return null;
        for (const g of d.recent || []) {
          if (g.date !== props.date) continue;
          for (const e of g.entries || []) {
            if (e.username === props.username) return e;
          }
        }
        return null;
      });

      const msgs = reactive({ loading: false, error: null, data: null });
      let loadedFor = "";
      let messageReq = 0;

      async function loadMessages(force) {
        const e = entry.value;
        if (!e || !["collected", "collection_failed"].includes(e.collectionState)) return;
        const key = props.username + "@" + props.date;
        if (!force && loadedFor === key) return;
        loadedFor = key;
        const my = ++messageReq;
        msgs.loading = true;
        msgs.error = null;
        msgs.data = null;
        try {
          const d = await getJSON(
            `/api/messages?date=${encodeURIComponent(props.date)}` +
              `&username=${encodeURIComponent(props.username)}&limit=40`
          );
          if (my === messageReq) msgs.data = d;
        } catch (err) {
          if (my === messageReq) msgs.error = err.message;
        } finally {
          if (my === messageReq) msgs.loading = false;
        }
      }

      async function loadMore() {
        const d = msgs.data;
        if (!d || !d.has_more || msgs.loading) return;
        const my = ++messageReq;
        msgs.loading = true;
        msgs.error = null;
        try {
          const next = await getJSON(
            `/api/messages?date=${encodeURIComponent(props.date)}` +
              `&username=${encodeURIComponent(props.username)}` +
              `&offset=${d.offset + d.limit}&limit=${d.limit}`
          );
          if (my === messageReq) {
            next.messages = d.messages.concat(next.messages);
            msgs.data = next;
          }
        } catch (err) {
          if (my === messageReq) msgs.error = err.message;
        } finally {
          if (my === messageReq) msgs.loading = false;
        }
      }

      watch(
        entry,
        (e) => {
          if (e) loadMessages();
          emit("nav-rows", []);
        },
        { immediate: true }
      );
      watch(
        () => [props.username, props.date],
        () => {
          loadedFor = "";
          messageReq++;
          msgs.data = null;
          msgs.error = null;
          loadEntry();
        },
        { immediate: true }
      );

      const isText = (t) => !t || t === "text";

      return { entry, remote, loadEntry, msgs, loadMessages, loadMore,
               meta, num, md, weekday, isText, hm };
    },
    template: `
      <div>
        <div class="banner" v-if="remote.loading && !entry" aria-live="polite">正在读取这个交点…</div>
        <div class="banner err" v-else-if="remote.error" role="alert">
          明细取不到：{{ remote.error }}
          <button type="button" class="btn" @click="loadEntry">重试</button>
        </div>
        <EmptyBox v-else-if="!entry"
          title="没有这个归档交点"
          body="它可能从未采集过；可以回群时间线或当天总览另选。" />

        <template v-else>
          <div class="crumb">
            <a :href="'/c/' + encodeURIComponent(entry.username)">{{ entry.chat }}</a>
            <span class="sep" aria-hidden="true">›</span>{{ date }}
            <span class="sep" aria-hidden="true">›</span>
            <a :href="'/d/' + date">当天全部群</a>
          </div>

          <div class="hd">
            <div>
              <h1>{{ entry.chat }}</h1>
              <div class="sub">{{ date }} {{ weekday(date) }} · <EntryStatus :entry="entry" /></div>
            </div>
            <div class="pager"><a :href="'/d/' + date">当天全部群</a></div>
          </div>

          <div class="panel">
            <div class="kv">
              <div>消息<b>{{ num(entry.total) }}</b></div>
              <div>发言人数<b>{{ num(entry.unique_senders) }}</b></div>
              <div>字数<b>{{ num(entry.chars) }}</b></div>
              <div>状态<b class="kv-big">{{ meta(entry.state).label }}</b></div>
            </div>
            <p class="note tight mt-block">
              {{ meta(entry.state).note }}
              · 归档 {{ entry.archived_at || '—' }}
              · 生成 {{ entry.composed_at || '—' }}
            </p>
          </div>

          <div class="banner" :class="{err: ['collection_failed','report_failed','orphan'].includes(entry.state)}">
            {{ meta(entry.state).note }}
          </div>
          <div class="banner err" v-if="entry.collectionState === 'collection_failed' && entry.state !== 'collection_failed'">
            本次采集失败，下面保留已有日报；不能据此认定本次采集成功。
          </div>
          <div class="banner err" v-for="(issue, i) in entry.collection?.coverage?.issues || []" :key="i" role="status">
            <b>{{ issue.code || 'COLLECTION_FAILED' }}</b> · {{ issue.message }}
            <span v-if="issue.retryable === false">请先在 WorkBuddy 中修复上述问题，再重新采集。</span>
            <span v-else>请在 WorkBuddy 中核对问题，再决定是否重新采集。</span>
          </div>
          <WorkBuddyAction :username="username" :date="date" />

          <template v-if="entry.html_url || entry.png_url">
            <div class="btns">
              <a v-if="entry.html_url" class="btn" :href="entry.html_url" target="_blank" rel="noopener">打开日报 HTML</a>
              <a v-if="entry.png_url" class="btn" :href="entry.png_url" download>下载长图</a>
              <a class="btn quiet" :href="'/c/' + encodeURIComponent(entry.username)">看这个群的历史</a>
            </div>
            <p v-if="!entry.png_url" class="note">未提供长图，可阅读 HTML 日报。</p>
            <iframe v-if="entry.html_url" class="report" :src="entry.html_url" title="日报" sandbox></iframe>
            <img v-else class="reportimg" :src="entry.png_url" alt="日报长图" />
          </template>
          <template v-else>
            <div class="panel" v-if="msgs.loading && !msgs.data">
              <div class="skeleton skel-40"></div>
              <div class="skeleton skel-40"></div>
            </div>

            <div class="banner err" v-else-if="msgs.error && !msgs.data" role="alert">
              原始记录取不到：{{ msgs.error }}
              <button type="button" class="btn" @click="loadMessages(true)">重试</button>
            </div>

            <div class="panel" v-else-if="msgs.data && msgs.data.messages.length">
              <div class="rowline mb-tight">
                <b class="fs-14">原始记录</b>
                <span class="note tight">
                  已显示 {{ msgs.data.messages.length }} / {{ num(msgs.data.total) }} 条
                </span>
              </div>
              <div class="msg" v-for="(m, i) in msgs.data.messages" :key="i">
                <span class="tm">{{ hm(m.time) }}</span>
                <span class="who">{{ m.sender }}</span>
                <span class="tick" v-if="!isText(m.type)">[{{ m.type }}]</span>{{ m.text }}
              </div>
              <div class="banner err" v-if="msgs.error" role="alert">
                后一页没取到，已显示的记录还在：{{ msgs.error }}
                <button type="button" class="btn" @click="loadMore">重试这一页</button>
              </div>
              <div class="btns mb-0" v-if="msgs.data.has_more && !msgs.error">
                <button class="btn" @click="loadMore" :disabled="msgs.loading">
                  {{ msgs.loading ? '正在取…' : '再看 40 条' }}
                </button>
              </div>
            </div>

            <EmptyBox v-else-if="msgs.data"
              title="这一天没有可显示的原始记录"
              body="本页没有可显示的消息；采集是否完成以采集状态为准。" />
          </template>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：矩阵

  const MatrixView = {
    props: ["data", "span"],
    emits: ["nav-rows"],
    components: { EmptyBox },
    setup(props, { emit }) {
      const table = computed(() => {
        const m = props.data && props.data.matrix;
        if (!m || !m.rows.length || !m.dates.length) return null;
        const dates = m.dates.slice(-props.span);
        const rows = m.rows.map(r => ({ ...r, cells: dates.map(date => {
          const c = (r.cells || []).find(c => c.date === date);
          return c ? { ...c, symbol: meta(c.state).label } : { date, state: "unknown", symbol: "未核验", blank: true };
        }) }));
        return { dates, rows, cols: dates.map(date => ({ key: date, label: md(date) })), nodata: 0 };
      });

      watch(
        table,
        (t) => {
          if (!t) return emit("nav-rows", []);
          const rows = [];
          t.rows.forEach((r) => {
            r.cells.forEach((c) => {
              if (c.blank) return; // 整列无归档：点进去也没有东西可看
              rows.push({
                href: detailURL(r.username, c.date),
                label: `${r.chat} ${c.date}`,
              });
            });
          });
          emit("nav-rows", rows);
        },
        { immediate: true }
      );

      /** 取某行在某列上的格子；开头那段压缩列没有具体日期，天然是空格 */
      const cellFor = (r, col) => {
        if (col.key === "lead") return { blank: true, symbol: "", date: "" };
        const c = r.cells.find((x) => x.date === col.key);
        return c || { blank: true, symbol: "", date: col.key };
      };

      return { table, num, md, detailURL, cellFor };
    },
    template: `
      <div>
        <div class="hd">
          <div>
            <h1>矩阵</h1>
            <div class="sub" v-if="table">
              最近 <b>{{ table.dates.length }}</b> 个日历日
              · <b>{{ table.rows.length }}</b> 个群
              <template v-if="table.nodata">
                · 其中 <b>{{ table.nodata }}</b> 天整体没有归档
              </template>
            </div>
          </div>
          <div class="tabs">
            <a href="/dates">按日期</a>
            <a href="/chats">按群</a>
          </div>
        </div>

        <EmptyBox v-if="!table" title="还没有归档数据" body="请在 WorkBuddy 中核对关注群与需要采集的日期。" />

        <template v-else>
          <div class="scroll">
            <table class="mx">
              <thead>
                <tr>
                  <th class="side" scope="col"><span class="sr-only">群</span></th>
                  <th v-for="col in table.cols" :key="col.key" scope="col"
                      :class="{ nd: col.blank, lead: col.key === 'lead' }">{{ col.label }}</th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="r in table.rows" :key="r.username">
                  <th class="chat" scope="row">
                    <a :href="'/c/' + encodeURIComponent(r.username)">{{ r.chat }}</a>
                  </th>
                  <td class="c" v-for="col in table.cols" :key="col.key"
                      :class="[ 'c-' + cellFor(r, col).state, { 'c-nodata': col.blank } ]">
                    <a v-if="!cellFor(r, col).blank" :href="detailURL(r.username, col.key)"
                       :aria-label="r.chat + ' ' + col.key + ' ' + cellFor(r, col).symbol">{{ cellFor(r, col).symbol }}</a><span v-else>未核验</span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <p class="note">每格显示服务提供的采集或日报状态。未返回的交点显示“未核验”，不推断历史关注范围；打开交点可分别核对采集与日报。</p>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：搜索

  const SearchView = {
    props: ["data", "filters", "chats"],
    emits: ["nav-rows", "do-search"],
    components: { EmptyBox },
    setup(props, { emit }) {
      const local = reactive({ q: "", chat: "", from: "", to: "", error: "" });
      watch(() => props.filters, filters => Object.assign(local, filters), { immediate: true });
      function submit() {
        local.error = local.from && local.to && local.from > local.to ? "开始日期不能晚于结束日期。" : "";
        if (!local.error) emit("do-search", { q: local.q.trim(), chat: local.chat, from: local.from, to: local.to });
      }

      const nav = computed(() => {
        const d = props.data;
        if (!d || !d.search || !d.search.results) return [];
        return d.search.results.map((r) => ({
          href: detailURL(r.username, r.date),
          label: `${r.sender} ${md(r.date)}`,
        }));
      });

      watch(nav, (v) => emit("nav-rows", v), { immediate: true });

      return { local, submit, highlight, num, md, detailURL };
    },
    template: `
      <div>
        <div class="hd">
          <div>
            <h1>搜索</h1>
            <div class="sub">
              跨群跨天搜消息正文。按 <kbd>/</kbd> 随时回到这里。
            </div>
          </div>
        </div>

        <form class="searchbox" @submit.prevent="submit">
          <input type="search" name="q" v-model="local.q" maxlength="200" required
                 placeholder="输入消息关键词…"
                 aria-label="搜索消息" autocomplete="off" />
          <button class="btn" type="submit">搜索</button>
          <div class="search-filters">
            <label>群<select name="chat" v-model="local.chat"><option value="">全部群</option><option v-for="c in chats" :key="c.username" :value="c.username">{{ c.chat }} · {{ c.username }}</option></select></label>
            <label>开始日期<input type="date" name="from" v-model="local.from" /></label>
            <label>结束日期<input type="date" name="to" v-model="local.to" /></label>
          </div>
          <p v-if="local.error" class="filter-error" role="alert">{{ local.error }}</p>
        </form>

        <div class="hint" v-if="!data || !data.search || data.search.done === false">
          输入至少一个字开始搜。当前库里只有归档过的消息能被搜到。
        </div>

        <div class="banner" v-if="data && data.search && data.search.loading">
          正在搜「{{ data.search.q }}」…
        </div>

        <div class="banner err" v-if="data && data.search && data.search.error" role="alert">
          {{ data.search.error }}
        </div>

        <template v-if="data && data.search && data.search.done && data.search.results">
          <div class="sub mb-block">
            「{{ data.search.q }}」命中 <b>{{ num(data.search.count) }}</b> 条
            <template v-if="data.search.truncated">（只显示前 {{ data.search.count }} 条，收窄条件再试）</template>
          </div>

          <EmptyBox v-if="!data.search.results.length"
            title="没有命中"
            body="换个词试试。中文搜索是子串匹配，两个字的词也能搜到。" />

          <div class="list" v-else>
            <a class="item stack" v-for="(r, i) in data.search.results" :key="r.username + '@' + r.date + '@' + i"
               :href="detailURL(r.username, r.date)">
              <div class="hit-top">
                <span class="d">{{ md(r.date) }}</span>
                <span class="t">
                  <span class="note">{{ r.chat || r.username }} · {{ r.username }}</span>
                  <span class="note"> · {{ r.sender }}</span>
                </span>
                <span class="hit-time">{{ (r.time || '').slice(11) }}</span>
              </div>
              <div class="hit-text" v-html="highlight(r.text, data.search.q)"></div>
            </a>
          </div>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 根组件

  const App = {
    components: {
      Badge,
      EmptyBox,
      WorkBuddyAction,
      RecentView,
      DatesView,
      DayView,
      ChatsView,
      ChatView,
      DetailView,
      MatrixView,
      SearchView,
    },
    setup() {
      const store = reactive({
        loading: true,
        error: null,
        data: null,
        status: null,
        copyNotice: "",

        route: parseRoute(location.pathname + location.search),
        days: 7,
        span: 14,

        navRows: [],
        cursor: -1,

        search: {
          q: "",
          results: null,
          count: 0,
          truncated: false,
          loading: false,
          error: null,
          done: false,
        },

        helpOpen: false,
      });

      // ---------- 数据

      async function loadBrowse() {
        store.loading = true;
        store.copyNotice = "";
        store.error = null;
        store.data = null;
        store.status = null;
        try {
          store.status = await getJSON("/api/status");
          if (store.status.reading?.available !== true) {
            store.data = null;
            store.error = null;
            return;
          }
          store.data = await getJSON("/api/browse?days=30");
          store.error = null;
        } catch (e) {
          store.error = "拿不到数据：" + e.message;
        } finally {
          store.loading = false;
        }
      }

      const setupTitle = computed(() => {
        const code = store.status?.reading?.code;
        if (code === "CONFIG_INVALID") return "先检查这台电脑的配置";
        if (code === "INDEX_NOT_READY") return "配置已保存，继续准备首份日报";
        if (code === "INDEX_INVALID") return "先恢复阅读索引";
        return "从第一份群日报开始";
      });

      const setupRequest = computed(() => {
        const code = store.status?.reading?.code;
        if (code === "CONFIG_INVALID")
          return "请使用微信群日报 Skill，检查并修复这台电脑的配置，保留已有聊天归档和日报。";
        if (code === "INDEX_NOT_READY")
          return "请使用微信群日报 Skill，检查阅读数据，完成首次采集或恢复索引，并打开一份日报。";
        if (code === "INDEX_INVALID")
          return "请使用微信群日报 Skill，检查并恢复阅读索引，保留已有聊天归档和日报。";
        return "请使用微信群日报 Skill，带我检查环境、确认微信账号、选择关注群，并生成首份日报。";
      });

      async function copySetupRequest() {
        try {
          await copyText(setupRequest.value);
          store.copyNotice = "已复制，请粘贴到 WorkBuddy 对话。";
        } catch (e) {
          store.copyNotice = "未能自动复制，请选中上面的文字，复制到 WorkBuddy 对话。";
        }
      }

      // ---------- 导航

      // 浮层打开时锁住背景滚动。遮罩是 position:fixed，只盖视口；
      // 不锁的话滚轮还能把下面的页面推走，露出没被盖住的部分——一眼就看出是假的弹窗。
      watch(
        () => store.helpOpen,
        (open) => {
          document.body.style.overflow = open ? "hidden" : "";
          nextTick(() => {
            const dialog = document.getElementById("keyboard-help");
            if (open && dialog && !dialog.open) dialog.showModal();
            if (!open && dialog?.open) dialog.close();
          });
        }
      );

      function go(url, replace) {
        if (url === location.pathname + location.search) return;
        if (replace) history.replaceState({}, "", url);
        else history.pushState({}, "", url);
        store.route = parseRoute(url);
        store.cursor = -1;
        store.navRows = [];
        window.scrollTo({ top: 0, behavior: "instant" in window ? "instant" : "auto" });
        afterRoute();
      }

      function afterRoute() {
        if (store.status?.reading?.available !== true) return;
        if (store.route.name === "search") doSearch(store.route.filters);
        else {
          searchReq++;
          store.search.loading = false;
          store.search.done = false;
        }
      }

      // ---------- 搜索
      let searchReq = 0;
      async function doSearch(filters) {
        const q = filters.q || "";
        const params = new URLSearchParams();
        for (const key of ["q", "chat", "from", "to"]) if (filters[key]) params.set(key, filters[key]);
        const want = "/search" + (params.size ? "?" + params : "");
        if (location.pathname + location.search !== want) {
          history.replaceState({}, "", want);
          store.route = parseRoute(want);
        }
        const my = ++searchReq;
        Object.assign(store.search, { q, results: null, count: 0, error: null, done: false, loading: !!q });
        if (!q) return;
        if (filters.from && filters.to && filters.from > filters.to) {
          store.search.error = "开始日期不能晚于结束日期。";
          store.search.loading = false;
          return;
        }
        try {
          const d = await getJSON("/api/search?" + params + "&limit=200");
          if (my !== searchReq) return;
          store.search.results = d.results || [];
          store.search.count = d.count || 0;
          store.search.truncated = !!d.truncated;
          store.search.done = true;
          store.cursor = -1;
        } catch (e) {
          if (my !== searchReq) return;
          store.search.error = e.message;
          store.search.done = true;
        } finally {
          if (my === searchReq) store.search.loading = false;
        }
      }

      // ---------- 键盘

      function focusSearch() {
        if (store.route.name !== "search") go("/search");
        nextTick(() => {
          const el = document.querySelector('input[type="search"]');
          if (el) {
            el.focus();
            el.select();
          }
        });
      }

      function openCursor() {
        const row = store.navRows[store.cursor];
        if (row) go(row.href);
      }

      function onKey(e) {
        const tag = (e.target && e.target.tagName) || "";
        const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(tag);

        if (store.helpOpen) {
          if (e.key === "Escape") { e.preventDefault(); store.helpOpen = false; }
          return;
        }
        if (e.key === "Escape") {
          if (typing) {
            e.target.blur();
            return;
          }
          back();
          return;
        }

        if (typing || /^(BUTTON|A|SUMMARY)$/.test(tag) || e.target?.isContentEditable) return;
        if (e.metaKey || e.ctrlKey || e.altKey) return;

        if (e.key === "/") {
          e.preventDefault();
          focusSearch();
          return;
        }
        if (e.key === "?") {
          e.preventDefault();
          store.helpOpen = !store.helpOpen;
          return;
        }

        if (e.key === "j" || e.key === "ArrowDown") {
          if (!store.navRows.length) return;
          e.preventDefault();
          store.cursor = Math.min(store.cursor + 1, store.navRows.length - 1);
          scrollCursorIntoView();
          return;
        }
        if (e.key === "k" || e.key === "ArrowUp") {
          if (!store.navRows.length) return;
          e.preventDefault();
          store.cursor = Math.max(store.cursor - 1, 0);
          scrollCursorIntoView();
          return;
        }
        if (e.key === "Enter") {
          if (store.cursor >= 0) {
            e.preventDefault();
            openCursor();
          }
          return;
        }
        if (e.key === "g") {
          e.preventDefault();
          store.cursor = 0;
          scrollCursorIntoView();
          return;
        }
        if (e.key === "G") {
          e.preventDefault();
          store.cursor = store.navRows.length - 1;
          scrollCursorIntoView();
          return;
        }

        const map = { 1: "/", 2: "/dates", 3: "/chats", 4: "/matrix", 5: "/search" };
        if (map[e.key]) {
          e.preventDefault();
          go(map[e.key]);
        }
      }

      function scrollCursorIntoView() {
        nextTick(() => {
          const el = document.querySelector(".item.kb-cursor, .card.kb-cursor, [data-kb-current]");
          if (el && el.scrollIntoView) el.scrollIntoView({ block: "nearest" });
        });
      }

      function back() {
        if (history.length > 1) history.back();
        else go("/");
      }

      // ---------- 生命周期

      function onPop() {
        store.route = parseRoute(location.pathname + location.search);
        store.cursor = -1;
        store.navRows = [];
        afterRoute();
      }

      function onNavRows(rows) {
        store.navRows = rows || [];
        store.cursor = -1;
      }

      function pickDays(n) {
        store.days = n;
      }

      window.addEventListener("popstate", onPop);
      window.addEventListener("keydown", onKey);

      loadBrowse().then(afterRoute);

      // ---------- 派生

      const runStatus = computed(() => {
        const status = store.status || {};
        const schedule = status.schedule || {};
        const first = { not_observed: "未核验", running: "执行中", verified: "已核验可读", empty: "零消息", insufficient: "素材不足", failed: "失败" };
        const registered = schedule.registered === false ? "未登记"
          : schedule.registered === true && schedule.readback_at ? "已回读" : "待核验";
        return { first: status.first_report?.state === "verified" && !status.first_report.verified_at ? "未核验" : first[status.first_report?.state] || "未核验", registered,
          plan: schedule.trigger_time ? `配置意图 ${schedule.trigger_time}（${schedule.timezone || '时区未核验'}），为开始触发时间` : "触发时间未设置",
          observed: schedule.last_scheduled_run ? "已有记录，请在 WorkBuddy 中核对结果" : "尚未观察" };
      });

      const navActive = computed(() => store.route.key);

      const title = computed(() => {
        const r = store.route;
        if (r.name === "day") return r.date + " · 群日报";
        if (r.name === "chat") return "群时间线 · 群日报";
        if (r.name === "detail") return r.date + " · 群日报";
        if (r.name === "search") return "搜索 · 群日报";
        const m = { recent: "最近日报", dates: "按日期", chats: "按群", matrix: "矩阵" };
        return (m[r.name] || "群日报") + " · 群日报";
      });

      watch(title, (t) => {
        document.title = t;
      }, { immediate: true });

      // 键盘光标要落在正确的元素上：给当前视图的列表项打标记
      watch(
        () => store.cursor,
        (i) => {
          nextTick(() => {
            document.querySelectorAll("[data-kb-current]").forEach(el => {
              el.removeAttribute("data-kb-current"); el.classList.remove("kb-cursor");
            });
            const all = document.querySelectorAll(".item, .mini, .card, table.mx td.c a");
            const navRows = store.navRows;
            if (i < 0 || !navRows[i]) return;
            // 按 href 找对应元素，避免依赖渲染顺序
            const href = navRows[i].href;
            for (const el of all) {
              const a = el.tagName === "A" ? el : el.querySelector("a[href]");
              if (a && a.getAttribute("href") === href) {
                const host = el.closest(".item, .mini, .card") || el;
                host.classList.add("kb-cursor");
                host.setAttribute("data-kb-current", "1");
                break;
              }
            }
          });
        }
      );

      return {
        store,
        navActive,
        go,
        pickDays,
        doSearch,
        onNavRows,
        focusSearch,
        loadBrowse,
        setupTitle,
        runStatus,
        setupRequest,
        copySetupRequest,
      };
    },
    template: `
      <a class="skip-link" href="#reading-content">跳到正文</a>
      <header class="top">
        <a class="brand" href="/" @click.prevent="go('/')">群日报</a>
        <nav class="nav" aria-label="阅读导航">
          <a v-for="n in [
              {href:'/', label:'最近', key:'recent'},
              {href:'/dates', label:'按日期', key:'dates'},
              {href:'/chats', label:'按群', key:'chats'},
              {href:'/matrix', label:'矩阵', key:'matrix'},
              {href:'/search', label:'搜索', key:'search'}]"
             :key="n.key"
             :href="n.href"
             :class="{ on: navActive === n.key }"
             @click.prevent="go(n.href)">{{ n.label }}</a>
          <span class="grow"></span>
          <a class="search-pill" href="/search" @click.prevent="focusSearch">
            搜索 <kbd>/</kbd>
          </a>
        </nav>
      </header>

      <main id="reading-content" tabindex="-1">
        <div class="banner err" v-if="store.error" role="alert">
          {{ store.error }}
          <button type="button" class="btn quiet" @click="loadBrowse">重新检查</button>
        </div>

        <div v-if="store.loading" aria-busy="true" aria-live="polite">
          <div class="skeleton skel-56"></div>
          <div class="skeleton"></div>
          <div class="skeleton"></div>
          <div class="skeleton"></div>
        </div>

        <section v-else-if="store.status && store.status.reading?.available !== true"
          class="setup-state" aria-labelledby="setup-title">
          <div class="hd"><h1 id="setup-title">{{ setupTitle }}</h1></div>
          <p>{{ store.status.reading?.message || '阅读状态未核验，请在 WorkBuddy 中核对。' }}</p>
          <p class="setup-request">{{ setupRequest }}</p>
          <div class="btns">
            <button class="btn" type="button" @click="copySetupRequest">复制给 WorkBuddy 的话</button>
            <button class="btn quiet" type="button" @click="loadBrowse">重新检查</button>
          </div>
          <p class="setup-feedback" aria-live="polite">{{ store.copyNotice }}</p>
          <p class="setup-note">完成后，这里会显示各个关注群的日报；可按日期和群回看。首次配置与定时设置都在 WorkBuddy 对话中进行。</p>
        </section>

        <div v-else-if="store.data">
          <details class="run-status">
            <summary>运行状态 · 首报 {{ runStatus.first }} · 宿主任务 {{ runStatus.registered }}</summary>
            <p>{{ runStatus.plan }}；真实定时运行：{{ runStatus.observed }}。</p>
            <p>配置可读、首报核验、任务回读和定时成功分别记录。需要处理时，在 WorkBuddy 中核对。</p>
            <WorkBuddyAction />
          </details>
          <RecentView v-if="store.route.name === 'recent'"
            :data="store.data" :days="store.days"
            @nav-rows="onNavRows" @pick-days="pickDays" />

          <DatesView v-else-if="store.route.name === 'dates'"
            :data="store.data" @nav-rows="onNavRows" />

          <DayView v-else-if="store.route.name === 'day'"
            :data="store.data" :date="store.route.date" @nav-rows="onNavRows" />

          <ChatsView v-else-if="store.route.name === 'chats'"
            :data="store.data" @nav-rows="onNavRows" />

          <ChatView v-else-if="store.route.name === 'chat'"
            :data="store.data" :username="store.route.username" @nav-rows="onNavRows" />

          <DetailView v-else-if="store.route.name === 'detail'"
            :data="store.data" :username="store.route.username" :date="store.route.date"
            @nav-rows="onNavRows" />

          <MatrixView v-else-if="store.route.name === 'matrix'"
            :data="store.data" :span="store.span" @nav-rows="onNavRows" />

          <SearchView v-else-if="store.route.name === 'search'"
            :data="store" :filters="store.route.filters" :chats="store.data.chats || []" @nav-rows="onNavRows" @do-search="doSearch" />

          <div v-else-if="store.route.name === 'notfound'">
            <div class="hd"><h1>页面不存在</h1></div>
            <div class="emptybox"><a href="/" @click.prevent="go('/')">回首页</a></div>
          </div>
        </div>
      </main>

      <footer class="foot">
        本机只读 · 只监听 127.0.0.1
        <template v-if="store.data && store.data.overview">
          · {{ store.data.overview.entries }} 条归档
          · {{ store.data.overview.msgs }} 条消息
          · {{ store.data.overview.reports }} 份日报
        </template>
        · 按 <kbd>?</kbd> 看快捷键
      </footer>

      <dialog id="keyboard-help" class="help-scrim" aria-labelledby="help-title"
           @cancel.prevent="store.helpOpen = false" @click.self="store.helpOpen = false">
        <div class="help-panel">
          <h2 id="help-title">键盘快捷键</h2>
          <div class="help-keys">
            <div><kbd>1</kbd> 最近 · <kbd>2</kbd> 按日期 · <kbd>3</kbd> 按群 · <kbd>4</kbd> 矩阵 · <kbd>5</kbd> 搜索</div>
            <div><kbd>j</kbd> / <kbd>k</kbd> 上下移动　<kbd>g</kbd> / <kbd>G</kbd> 跳到首尾</div>
            <div><kbd>Enter</kbd> 进入光标项　<kbd>Esc</kbd> 返回</div>
            <div><kbd>/</kbd> 聚焦搜索　<kbd>?</kbd> 打开这张表</div>
          </div>
          <p class="help-foot">输入框里按 Esc 会先退出输入，不会离开页面。</p>
          <button type="button" class="btn quiet" @click="store.helpOpen = false">关闭快捷键</button>
        </div>
      </dialog>`,
  };

  createApp(App).mount("#app");
})();
