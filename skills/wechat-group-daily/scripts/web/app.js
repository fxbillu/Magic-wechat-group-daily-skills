/* 群日报工作台 · 前端
 *
 * 无构建链。Vue 3 从本地 vendor 加载，模板是字符串。
 * 数据只从 /api/browse · /api/search · /api/messages 拿，不直连 SQLite。
 *
 * 五态是全产品的判断机制，因此只在 STATE_META 里定义一次，
 * 所有表面（徽章 / 卡片标题 / 圆点 / 矩阵 / 明细页）都从这里取词。
 */
(function () {
  "use strict";

  const { createApp, reactive, computed, watch, nextTick } = Vue;

  // ────────────────────────────────────────────── 常量

  /** 五态。改这里就等于改全站文案。 */
  const STATE_META = {
    ready: {
      label: "已出日报",
      cls: "ready",
      title: "",                      // 有标题时用真标题，这里留空
      note: "日报已生成",
    },
    pending: {
      label: "未生成",
      cls: "pending",
      title: "有内容，日报还没生成",
      note: "素材够了，等出稿",
    },
    orphan: {
      label: "数据缺失",
      cls: "orphan",
      title: "日报在，原始归档不在了",
      note: "产物可能是死的",
    },
    empty: {
      label: "素材不足",
      cls: "empty",
      title: "素材不足，未成篇",
      note: "这天本来就没东西，不是欠账",
    },
    missing: {
      label: "无对话",
      cls: "missing",
      title: "这一天没有归档",
      note: "监控中，采集没拿到",
    },
  };

  const FALLBACK_STATE = {
    label: "状态未知",
    cls: "missing",
    title: "状态未知",
    note: "数据层返回了未定义的状态，这是一个 bug",
  };

  const NAV = [
    { href: "/", label: "最近", key: "recent" },
    { href: "/dates", label: "按日期", key: "dates" },
    { href: "/chats", label: "按群", key: "chats" },
    { href: "/matrix", label: "矩阵", key: "matrix" },
    { href: "/search", label: "搜索", key: "search" },
  ];

  const DAY_TABS = [3, 7, 14, 30];

  /** 出报通常在这个时刻之后。首屏用它区分「还没到点」与「真没出」。 */
  const REPORT_HOUR = 10;
  const REPORT_MIN = 30;

  // ────────────────────────────────────────────── 工具

  const pad2 = (n) => String(n).padStart(2, "0");

  function todayISO() {
    const d = new Date();
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
  }

  function parseISO(s) {
    const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(s || "");
    if (!m) return null;
    return new Date(+m[1], +m[2] - 1, +m[3]);
  }

  function shiftDays(s, n) {
    const d = parseISO(s);
    if (!d) return s;
    d.setDate(d.getDate() + n);
    return `${d.getFullYear()}-${pad2(d.getMonth() + 1)}-${pad2(d.getDate())}`;
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
    return (Number(n) || 0).toLocaleString("zh-CN");
  }

  function pct(part, whole) {
    if (!whole) return 0;
    return Math.round((part / whole) * 100);
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
    return STATE_META[state] || FALLBACK_STATE;
  }

  function reportURL(rel) {
    return "/r/" + rel.split("/").map(encodeURIComponent).join("/");
  }

  function chatURL(username) {
    return "/c/" + encodeURIComponent(username);
  }

  function detailURL(username, date) {
    return "/c/" + encodeURIComponent(username) + "/" + date;
  }

  /** 判断「今天」是否还没到出报时刻 */
  function beforeReportHour() {
    const d = new Date();
    return d.getHours() * 60 + d.getMinutes() < REPORT_HOUR * 60 + REPORT_MIN;
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
      if (e && e.name === "AbortError") {
        throw new Error("本机服务响应超时，请确认采集或索引没有卡住");
      }
      throw new Error("连不上本机服务，请在 WorkBuddy 中重新启动群日报阅读服务，再重新检查");
    } finally {
      clearTimeout(timer);
    }

    let body = null;
    try {
      body = await r.json();
    } catch (e) {
      throw new Error(`响应不是 JSON（HTTP ${r.status}）`);
    }
    if (!r.ok) {
      throw new Error((body && body.error) || `HTTP ${r.status}`);
    }
    return body;
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
      return { name: "search", key: "search", q: u.searchParams.get("q") || "" };

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
    components: { Badge, Dot, EmptyBox },
    setup(props, { emit }) {
      const groups = computed(() => {
        const d = props.data;
        if (!d || !d.recent) return [];
        const limit = props.days;
        const slice = d.recent.slice(0, limit);
        const followed = (d.chats || []).filter((c) => c.followed);

        return slice.map((g) => {
          const entries = g.entries || [];
          const have = new Set(entries.map((e) => e.username));
          const holes = followed.filter((c) => !have.has(c.username));

          const byState = { ready: 0, pending: 0, orphan: 0, empty: 0, missing: 0 };
          entries.forEach((e) => {
            byState[e.state] = (byState[e.state] || 0) + 1;
          });
          byState.missing += holes.length;

          const expected = entries.length + holes.length;
          return {
            date: g.date,
            entries,
            holes,
            byState,
            expected,
            total: g.total,
          };
        });
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
        const date = t.date;
        const isToday = date === todayISO();
        const ready = t.reports || 0;
        const pend = t.pending || 0;
        const chats = t.chats || [];
        const empty = chats.filter((c) => c.state === "empty").length;
        const miss = t.missing || 0;

        // 口径必须分开算：`today.chats` 里已经含着 missing 的群
        // （by_day 用 include_configured 补进来的），再拿 t.missing 往上加
        // 就是把没归档的群数了两遍，出现「3 个群中 2 个有归档」而实际只有 1 个。
        // 分母 = 关注名单 ∪ 当天有归档的群；分子 = 真正有归档的群。
        const archived = chats.filter((c) => c.state !== "missing").length;
        const followedU = ((props.data && props.data.chats) || [])
          .filter((c) => c.followed)
          .map((c) => c.username);
        const expected = new Set(
          chats.map((c) => c.username).concat(followedU)
        ).size;

        let head;
        if (ready > 0) {
          head = `已出 ${ready} 份日报`;
        } else if (isToday && beforeReportHour()) {
          head = "今天的日报还没到点";
        } else {
          head = "今天一份日报都还没出";
        }

        const bits = [];
        bits.push(`${expected} 个群中 ${archived} 个有归档`);
        if (pend) bits.push(`未生成 ${pend}`);
        if (empty) bits.push(`素材不足 ${empty}`);
        if (miss) bits.push(`无归档 ${miss}`);

        let note = "";
        if (ready === 0 && isToday && beforeReportHour()) {
          note = `出报通常在 ${REPORT_HOUR}:${pad2(REPORT_MIN)} 之后`;
        } else if (!isToday) {
          note = `${agoText(date)}（最近一次归档）`;
        }

        return { date, isToday, head, bits, note, ready, expected, miss, archived };
      });

      const dateTitle = (ds) => {
        const a = agoText(ds);
        return a && a !== ds ? a : ds;
      };

      return { groups, todayLine, dateTitle, md, num, weekday, reportURL, detailURL, scrollX: 0 };
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

        <!-- 今天的状态条：替掉「今天 0 份日报」那种把「还没到点」渲染成「失败」的做法 -->
        <div class="todaybar" v-if="todayLine">
          <span class="tb-date">{{ todayLine.date }} {{ weekday(todayLine.date) }}</span>
          <span class="tb-main">
            <b v-if="todayLine.ready">{{ todayLine.ready }}</b>{{ todayLine.head }}
          </span>
          <span class="tb-note">{{ todayLine.bits.join(' · ') }}</span>
          <span class="tb-drop"></span>
          <span class="tb-note" v-if="todayLine.note">{{ todayLine.note }}</span>
        </div>

        <EmptyBox v-if="!groups.length"
          title="还没有任何归档"
          body="先跑 python fetch.py archive --config --days 7 采集一轮。" />

        <section class="daygroup" v-for="g in groups" :key="g.date">
          <div class="dhead">
            <a :href="'/d/' + g.date">
              <b>{{ g.date }}</b>
              <span class="wd">{{ weekday(g.date) }} · {{ dateTitle(g.date) }}</span>
            </a>
            <span class="st">
              已出 {{ g.byState.ready }} / {{ g.expected }}
              <template v-if="g.byState.pending"> · 未生成 {{ g.byState.pending }}</template>
              <template v-if="g.byState.empty"> · 素材不足 {{ g.byState.empty }}</template>
              <template v-if="g.byState.orphan"> · 数据缺失 {{ g.byState.orphan }}</template>
              <template v-if="g.byState.missing"> · 无归档 {{ g.byState.missing }}</template>
              · {{ num(g.total) }} 条
            </span>
          </div>

          <div class="grid2">
            <article class="mini" v-for="e in g.entries" :key="e.username"
                     :class="{ 'no-thumb': !e.report_png }">
              <a class="card-link" :href="'/c/' + encodeURIComponent(e.username) + '/' + g.date"
                 :aria-label="e.chat + ' ' + g.date + ' ' + e.state"></a>
              <div class="mthumb" v-if="e.report_png">
                <img :src="reportURL(e.report_png)" alt="" loading="lazy" />
              </div>
              <div class="mbody">
                <a class="mname" :href="'/c/' + encodeURIComponent(e.username)">{{ e.chat }}</a>
                <div class="mttl" :class="{ quiet: !e.title }">
                  {{ e.title || (e.state === 'ready' ? '（标题缺失）' : '')
                     || (e.state === 'pending' ? '有内容，日报还没生成' : '')
                     || (e.state === 'empty' ? '素材不足，未成篇' : '')
                     || (e.state === 'orphan' ? '日报在，原始归档不在了' : '')
                     || (e.state === 'missing' ? '这一天没有归档' : '') }}
                </div>
                <div class="mmeta">
                  <span>{{ num(e.total) }} 条</span>
                  <template v-if="e.composed_at">· <span>{{ e.composed_at.slice(5, 16) }}</span></template>
                  <Badge :state="e.state" />
                </div>
              </div>
            </article>
          </div>

          <p class="note" v-if="g.holes.length">
            另有 {{ g.holes.length }} 个关注中的群当天没有归档：
            <template v-for="(h, i) in g.holes" :key="h.username">
              <a :href="'/c/' + encodeURIComponent(h.username)">{{ h.chat }}</a><template v-if="i < g.holes.length - 1">、</template>
            </template>
          </p>
        </section>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：按日期

  const DatesView = {
    props: ["data"],
    emits: ["nav-rows"],
    components: { Dot, EmptyBox },
    setup(props, { emit }) {
      /** 在日期差 > 1 处插入断更条——失败必须是可见的 */
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
          const ready = a ? a.ready : 0;
          const pend = a ? a.pending : 0;
          const empty = a ? a.empty : 0;

          out.push({
            type: "day",
            date,
            chats: a ? a.chats : entries.length,
            total: a ? a.total : 0,
            ready,
            pend,
            empty,
            // 没有聚合行时不要断言「无归档」，宁可留空——说错了比不说明更糟
            state: a
              ? ready ? "ready" : pend ? "pending" : empty ? "empty" : "missing"
              : null,
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
              · 虚线处是断更
            </div>
          </div>
          <div class="tabs"><a href="/matrix">看矩阵 ›</a></div>
        </div>

        <EmptyBox v-if="!rows.length" title="还没有归档" body="先跑一轮 archive。" />

        <div class="list" v-else>
          <template v-for="(r, i) in rows" :key="i">
            <a v-if="r.type === 'day'" class="item" :href="'/d/' + r.date">
              <span class="d"><Dot :state="r.state" />{{ md(r.date) }}</span>
              <span class="t">
                {{ weekday(r.date) }}
                <span class="note"> · {{ r.chats }} 个群有归档 · {{ num(r.total) }} 条</span>
              </span>
              <span class="n">
                已出 {{ r.ready }}
                <template v-if="r.pend"> · 待 {{ r.pend }}</template>
                <template v-if="r.empty"> · 空 {{ r.empty }}</template>
              </span>
            </a>
            <div v-else class="gapbar">
              <span class="gap-line"></span>
              <span>{{ r.from }} → {{ r.to }} 之间断了 {{ r.missed }} 天</span>
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
    components: { Badge, EmptyBox },
    setup(props, { emit }) {
      const remote = reactive({ loading: false, error: null, data: null });
      let requestId = 0;

      async function loadDay() {
        const date = props.date;
        const my = ++requestId;
        remote.loading = true;
        remote.error = null;
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
        // 先用 browse 缓存立即出屏，再用独立接口补齐窗口外的日期与 missing 群。
        const d = props.data;
        const cached = d && (d.recent || []).find((x) => x.date === props.date);
        const g = remote.data || cached;
        if (!g) return null;
        // g 有两个来源，而 `chats` 在两边的类型不一样：
        // browse 的 recent[] 里是数字（当天有几个群），/api/day 里是数组（群列表）。
        // 早期写成 `g.chats || g.entries`，走缓存分支时拿到数字 2，
        // 接着 2.map(...) 抛错、整页白屏。只认数组，不是数组就退回 entries。
        const entries = Array.isArray(g.chats) ? g.chats : g.entries || [];
        if (remote.data) return { ...g, entries, holes: [] };

        const followed = ((d && d.chats) || []).filter((c) => c.followed);
        const have = new Set(entries.map((e) => e.username));
        const holes = followed.filter((c) => !have.has(c.username));
        return { ...g, entries, holes };
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
        const ents = g.entries || [];
        const c = { ready: 0, pending: 0, orphan: 0, empty: 0, missing: g.holes.length };
        ents.forEach((e) => {
          c[e.state] = (c[e.state] || 0) + 1;
        });
        return { counts: c, expected: ents.length + g.holes.length, total: g.total };
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

      return { day, nav, stats, remote, loadDay, meta, num, weekday, reportURL, detailURL, chatURL, md };
    },
    template: `
      <div>
        <div class="banner" v-if="remote.loading && !day" aria-live="polite">正在读取这一天…</div>
        <div class="banner err" v-else-if="remote.error && !day" role="alert">
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
                · {{ (day.entries || []).length }} 个群有归档
                · <b>{{ num(stats.total) }}</b> 条
                · 已出 <b>{{ stats.counts.ready }}</b> / {{ stats.expected }}
                <template v-if="stats.counts.pending"> · 未生成 {{ stats.counts.pending }}</template>
                <template v-if="stats.counts.empty"> · 素材不足 {{ stats.counts.empty }}</template>
                <template v-if="stats.counts.orphan"> · 数据缺失 {{ stats.counts.orphan }}</template>
                <template v-if="stats.counts.missing"> · 无归档 {{ stats.counts.missing }}</template>
              </div>
            </div>
            <div class="pager">
              <a v-if="nav.older" :href="'/d/' + nav.older">‹ {{ md(nav.older) }}（更早）</a>
              <a v-if="nav.newer" :href="'/d/' + nav.newer">{{ md(nav.newer) }}（更新）›</a>
            </div>
          </div>

          <article class="card" v-for="c in day.entries" :key="c.username"
                   :class="{ 'no-thumb': !c.report_png }">
            <a class="card-link" :href="detailURL(c.username, date)"
               :aria-label="c.chat + ' ' + date"></a>
            <div class="thumb" v-if="c.report_png">
              <img :src="reportURL(c.report_png)" alt="" loading="lazy" />
            </div>
            <div class="body">
              <div class="rowline">
                <a class="name" :href="chatURL(c.username)">{{ c.chat }}</a>
                <Badge :state="c.state" />
              </div>
              <div class="ttl" :class="{ nil: !c.title }">
                {{ c.title || (c.state === 'ready' ? '（日报标题缺失）' : '')
                   || (c.state === 'pending' ? '有内容，日报还没生成' : '')
                   || (c.state === 'empty' ? '素材不足，未成篇' : '')
                   || (c.state === 'orphan' ? '日报在，但原始归档不在了' : '')
                   || (c.state === 'missing' ? '这一天没有归档' : '') }}
              </div>
              <div class="lead" v-if="c.lead">{{ c.lead }}</div>
              <div class="ft">
                <span>{{ num(c.total) }} 条 · {{ num(c.unique_senders) }} 人 · {{ num(c.chars) }} 字</span>
                <a :href="chatURL(c.username)">历史 ›</a>
                <a v-if="c.report_png" :href="reportURL(c.report_png)" target="_blank" rel="noopener">长图</a>
                <a v-if="c.report_html" :href="reportURL(c.report_html)" target="_blank" rel="noopener">日报</a>
              </div>
            </div>
          </article>

          <p class="note" v-if="day.holes.length">
            监控中但没有归档的群：
            <template v-for="(h, i) in day.holes" :key="h.username">
              <a :href="chatURL(h.username)">{{ h.chat }}</a><template v-if="i < day.holes.length - 1">、</template>
            </template>
            —— 这些是「采集没拿到」，不是「没有对话」。
          </p>
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

      // 状态由后端给（`last_state`）。以前这里用
      // `reports>0 ? ready : total>0 ? pending : missing` 自己推，
      // 结果 `empty`（素材不足）被推成 `pending`（欠一份），
      // 群列表上就永远挂着一笔假账。
      const stateOf = (r) => r.last_state || "";

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
              · 关注名单改 config.json 的 chats
            </div>
          </div>
          <div class="tabs"><a href="/matrix">看矩阵 ›</a></div>
        </div>

        <EmptyBox v-if="!data || !(groups.followed.length || groups.others.length)"
          title="还没有归档，关注名单也是空的"
          body="先跑 python tools/setup.py 选群，再采集。" />

        <template v-else>
          <div class="sec">关注 的 群</div>
          <div class="list" v-if="groups.followed.length">
            <a class="item" v-for="r in groups.followed" :key="r.username" :href="'/c/' + encodeURIComponent(r.username)">
              <span class="d"><Dot :state="stateOf(r)" />{{ r.last_date ? md(r.last_date) : '—' }}</span>
              <span class="t">{{ r.chat }}
                <span class="note"> · {{ r.days }} 天 · {{ num(r.total) }} 条<template v-if="r.last_report"> · 最近日报 {{ md(r.last_report) }}</template><template v-else-if="r.days"> · 还没出过日报</template></span>
              </span>
              <span class="n">{{ r.reports }} 份</span>
            </a>
          </div>
          <EmptyBox v-else title="还没有关注的群"
            body="重跑 python tools/setup.py，或在 config.json 的 chats 里填。" />

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
    components: { Badge, EmptyBox },
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
        const totals = rs.filter((r) => r.total).map((r) => r.total);
        const avg = totals.length
          ? Math.round(totals.reduce((a, b) => a + b, 0) / totals.length)
          : 0;
        return {
          days: rs.length,
          avg,
          ready: rs.filter((r) => r.state === "ready").length,
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
        <div class="banner err" v-else-if="remote.error && !chat" role="alert">
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
            —— 群改名不会影响这条时间线，username 才是稳定主键
          </div>

          <div class="list">
            <a class="item" v-for="r in rows" :key="r.date" :href="detailURL(username, r.date)">
              <span class="d">{{ md(r.date) }}</span>
              <span class="t">{{ weekday(r.date) }}<span class="note" v-if="r.title"> · {{ r.title }}</span><span class="note" v-else> · {{ meta(r.state).title }}</span></span>
              <span class="n">{{ num(r.total) }}</span>
              <span class="n"><Badge :state="r.state" /></span>
            </a>
          </div>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：明细

  const DetailView = {
    props: ["data", "username", "date"],
    emits: ["nav-rows"],
    components: { Badge, EmptyBox },
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
        if (!e || e.state === "missing") return;
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
               meta, num, md, weekday, reportURL, isText, hm };
    },
    template: `
      <div>
        <div class="banner" v-if="remote.loading && !entry" aria-live="polite">正在读取这个交点…</div>
        <div class="banner err" v-else-if="remote.error && !entry" role="alert">
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
              <div class="sub">{{ date }} {{ weekday(date) }} · <Badge :state="entry.state" /></div>
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

          <!-- 有产物就摆出来：ready 直接看，orphan 先警告再给看 -->
          <template v-if="entry.report_html || entry.report_png">
            <div class="banner err" v-if="entry.state === 'orphan'">
              日报在，但这一天的原始归档不在了——下面这份产物可能是死的，
              点开之前先当它有风险。
            </div>
            <div class="btns">
              <a v-if="entry.report_html" class="btn" :href="reportURL(entry.report_html)"
                 target="_blank" rel="noopener">新窗口打开</a>
              <a v-if="entry.report_png" class="btn" :href="reportURL(entry.report_png)" download>下载长图</a>
              <a class="btn quiet" :href="'/c/' + encodeURIComponent(entry.username)">看这个群的历史</a>
            </div>
            <!--
              优先用长图：日报本来就是一张 900 宽的整页图（是为了转发做的），
              用 <img> 让它跟页面一起滚，比 iframe 里再套一根滚动条干净得多。
              iframe 只在"有 HTML 没 PNG"时兜底——那种情况很少，
              但真遇上时不能给一个打不开的空框。
            -->
            <img v-if="entry.report_png" class="reportimg"
                 :src="reportURL(entry.report_png)" alt="日报长图" />
            <iframe v-else class="report" :src="reportURL(entry.report_html)" title="日报"></iframe>
          </template>

          <!-- 没有日报：说清楚为什么，并把原始记录摆出来让人自己判断 -->
          <template v-else>
            <div class="banner" v-if="entry.state === 'pending'">
              有 {{ num(entry.total) }} 条消息（{{ num(entry.chars) }} 字），但日报还没生成。
              素材看起来是够的。
            </div>
            <div class="banner" v-else-if="entry.state === 'empty'">
              这一天有 {{ num(entry.total) }} 条消息，但素材不足以成篇——多半是单人在单向发布。
              <b>这不是欠账</b>，不用管它。
            </div>
            <div class="banner err" v-else-if="entry.state === 'orphan'">
              日报文件还在，但原始归档不见了（可能被清理过）。这份产物可能已经死了。
            </div>
            <div class="banner err" v-else-if="entry.state === 'missing'">
              这一天连归档都没有——采集断了。这不是「没有对话」。
            </div>

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
              body="归档里没有消息。" />
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
      /** 按日历连续生成列——断更处必须是可见的空列，不能从表里消失 */
      const table = computed(() => {
        const d = props.data;
        if (!d || !d.matrix || !d.matrix.rows.length) return null;

        const m = d.matrix;
        const anchor = m.dates.length ? m.dates[m.dates.length - 1] : null;
        if (!anchor) return null;

        const span = props.span;
        const dates = [];
        for (let i = span - 1; i >= 0; i--) dates.push(shiftDays(anchor, -i));

        const rows = m.rows.map((r) => {
          const byDate = {};
          (r.cells || []).forEach((c) => {
            byDate[c.date] = c;
          });
          const cells = dates.map((dt) => {
            const c = byDate[dt];
            if (!c) return { date: dt, state: "missing", total: 0, symbol: "·" };
            const state =
              c.state || (c.ready ? "ready" : c.total ? "pending" : "missing");
            const symbol =
              state === "missing" ? "·" : state === "empty" ? "–" : num(c.total);
            return { date: dt, state, total: c.total || 0, symbol };
          });
          return { username: r.username, chat: r.chat, cells };
        });

        // 整列无归档 ≠ 每个群各缺一天。
        // 前者是「这天没采到」（采集未覆盖 / 采集断了），后者是「这天有人聊、这个群没聊」。
        // 两者混成一片 `·`，十列结构性零值会把真正的空洞埋掉——
        // 所以整列无归档的列不出点，靠「有没有符号」而不是靠颜色区分。
        const hasCol = dates.map((dt, i) =>
          rows.some((r) => r.cells[i].state !== "missing")
        );
        rows.forEach((r) => {
          r.cells.forEach((c, i) => {
            if (!hasCol[i]) {
              c.blank = true;
              c.symbol = "";
            }
          });
        });

        // 开头那段「谁都没有归档」的日子是采集的起点边界，一列一天纯属占地方：
        // 十天十列长得一模一样，等于用半张表说一句话。压成一列写日期区间。
        // 区间内部的空白不压——那是采集真的断过，一天都得看见。
        const firstData = hasCol.indexOf(true);
        const leadEnd = firstData < 0 ? dates.length : firstData;
        const cols = [];
        if (leadEnd > 0) {
          const a = dates[0];
          const b = dates[leadEnd - 1];
          cols.push({
            key: "lead",
            label: leadEnd === 1 ? md(a) : `${md(a)}–${md(b)}`,
            blank: true,
            days: leadEnd,
          });
        }
        dates.slice(leadEnd).forEach((dt, i) => {
          const idx = leadEnd + i;
          cols.push({ key: dt, label: md(dt), blank: !hasCol[idx], days: 1 });
        });

        const nodata = hasCol.filter((x) => !x).length;
        const startLabel = firstData >= 0 ? dates[firstData] : null;
        return { dates, rows, hasCol, nodata, cols, startLabel, span };
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

        <EmptyBox v-if="!table" title="还没有归档数据" body="先跑一轮 archive。" />

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
                    <a v-if="!col.blank" :href="detailURL(r.username, col.key)"
                       :aria-label="r.chat + ' ' + col.key + ' ' + cellFor(r, col).state">{{ cellFor(r, col).symbol }}</a>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>

          <div class="legend">
            <span><span class="dot d-ready"></span>已出日报</span>
            <span><span class="dot d-pending"></span>有数据未生成</span>
            <span><span class="dot d-orphan"></span>数据缺失</span>
            <span><span class="dot d-empty"></span>素材不足（格内 –）</span>
            <span><span class="dot d-missing"></span>无归档（格内 ·）</span>
            <span><span class="dot d-nodata"></span>整体未采集（空格）</span>
          </div>

          <p class="note">
            后两态的底色几乎一样，所以另用符号兜底：<code>–</code> 是有归档但素材不够，
            <code>·</code> 是连归档都没有。整格空白表示这一天所有群都没有归档——
            那是采集的边界，不是哪个群欠了。
          </p>
        </template>
      </div>`,
  };

  // ────────────────────────────────────────────── 视图：搜索

  const SearchView = {
    props: ["data", "q"],
    emits: ["nav-rows", "do-search"],
    components: { EmptyBox },
    setup(props, { emit }) {
      const local = reactive({ text: props.q || "" });
      let timer = null;

      watch(
        () => props.q,
        (v) => {
          if (v !== local.text) local.text = v || "";
        }
      );

      function onInput() {
        clearTimeout(timer);
        timer = setTimeout(() => {
          emit("do-search", local.text.trim());
        }, 320);
      }

      function submit() {
        clearTimeout(timer);
        emit("do-search", local.text.trim());
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

      return { local, onInput, submit, highlight, num, md, detailURL };
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
          <input type="search" v-model="local.text" @input="onInput"
                 placeholder="搜一个词、一个人的名字、某个群的片段…"
                 aria-label="搜索消息" autocomplete="off" />
          <button class="btn" type="submit">搜索</button>
        </form>

        <div class="hint" v-if="!data || !data.search || data.search.done === false">
          输入至少一个字开始搜。当前库里只有归档过的消息能被搜到。
        </div>

        <div class="banner" v-if="data && data.search && data.search.loading">
          正在搜「{{ data.search.q }}」…
        </div>

        <div class="banner err" v-if="data && data.search && data.search.error">
          {{ data.search.error }}
        </div>

        <template v-if="data && data.search && data.search.results">
          <div class="sub mb-block">
            「{{ data.search.q }}」命中 <b>{{ num(data.search.count) }}</b> 条
            <template v-if="data.search.truncated">（只显示前 {{ data.search.count }} 条，收窄条件再试）</template>
          </div>

          <EmptyBox v-if="!data.search.results.length"
            title="没有命中"
            body="换个词试试。中文搜索是子串匹配，两个字的词也能搜到。" />

          <div class="list" v-else>
            <a class="item stack" v-for="(r, i) in data.search.results" :key="i"
               :href="detailURL(r.username, r.date)">
              <div class="hit-top">
                <span class="d">{{ md(r.date) }}</span>
                <span class="t">
                  <span class="note">{{ r.chat || r.username }}</span>
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
        try {
          store.status = await getJSON("/api/status");
          if (!store.status.reading.available) {
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
        const code = store.status && store.status.reading.code;
        if (code === "CONFIG_INVALID") return "先检查这台电脑的配置";
        if (code === "INDEX_NOT_READY") return "配置已保存，继续准备首份日报";
        if (code === "INDEX_INVALID") return "先恢复阅读索引";
        return "从第一份群日报开始";
      });

      const setupRequest = computed(() => {
        const code = store.status && store.status.reading.code;
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
          await navigator.clipboard.writeText(setupRequest.value);
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
        if (!store.status || !store.status.reading.available) return;
        const r = store.route;
        if (r.name === "search" && r.q && r.q !== store.search.q) {
          store.search.q = r.q;
          doSearch(r.q);
        }
        if (r.name !== "search") {
          store.search.done = false;
        }
      }

      // ---------- 搜索

      let searchReq = 0;

      async function doSearch(q) {
        store.search.q = q;
        if (!q) {
          Object.assign(store.search, {
            results: null, count: 0, loading: false, error: null, done: false,
          });
          go("/search", true);
          return;
        }
        // URL 与状态同步，但不要在已经搜过时反复 push
        const want = "/search?q=" + encodeURIComponent(q);
        if (location.pathname + location.search !== want) {
          history.replaceState({}, "", want);
          store.route = parseRoute(want);
        }

        const my = ++searchReq;
        store.search.loading = true;
        store.search.error = null;
        try {
          const d = await getJSON("/api/search?q=" + encodeURIComponent(q) + "&limit=200");
          if (my !== searchReq) return; // 后发先至的旧请求丢掉
          store.search.results = d.results || [];
          store.search.count = d.count || 0;
          store.search.truncated = !!d.truncated;
          store.search.done = true;
          store.cursor = -1;
          store.navRows = (d.results || []).map((r) => ({
            href: detailURL(r.username, r.date),
            label: `${r.sender} ${md(r.date)}`,
          }));
        } catch (e) {
          if (my !== searchReq) return;
          store.search.error = e.message;
          store.search.results = null;
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

        if (e.key === "Escape") {
          if (typing) {
            e.target.blur();
            return;
          }
          if (store.helpOpen) {
            store.helpOpen = false;
            return;
          }
          back();
          return;
        }

        if (typing) return;
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
            document.querySelectorAll("[data-kb-current]").forEach((el) => el.removeAttribute("data-kb-current"));
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
        setupRequest,
        copySetupRequest,
      };
    },
    template: `
      <header class="top">
        <a class="brand" href="/" @click.prevent="go('/')">群日报</a>
        <nav class="nav">
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

      <main>
        <div class="banner err" v-if="store.error">
          {{ store.error }}
          <span class="dismiss" @click="store.error = null">关闭</span>
        </div>

        <div v-if="store.loading" aria-busy="true" aria-live="polite">
          <div class="skeleton skel-56"></div>
          <div class="skeleton"></div>
          <div class="skeleton"></div>
          <div class="skeleton"></div>
        </div>

        <section v-else-if="store.status && !store.status.reading.available"
          class="setup-state" aria-labelledby="setup-title">
          <div class="hd"><h1 id="setup-title">{{ setupTitle }}</h1></div>
          <p>{{ store.status.reading.message }}</p>
          <p class="setup-request">{{ setupRequest }}</p>
          <div class="btns">
            <button class="btn" type="button" @click="copySetupRequest">复制给 WorkBuddy 的话</button>
            <button class="btn quiet" type="button" @click="loadBrowse">重新检查</button>
          </div>
          <p class="setup-feedback" aria-live="polite">{{ store.copyNotice }}</p>
          <p class="setup-note">完成后，这里会显示各个关注群的日报；可按日期和群回看。首次配置与定时设置都在 WorkBuddy 对话中进行。</p>
        </section>

        <div v-else-if="store.data">
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
            :data="store" :q="store.route.q" @nav-rows="onNavRows" @do-search="doSearch" />

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

      <div v-if="store.helpOpen" class="help-scrim"
           @click.self="store.helpOpen = false">
        <div class="help-panel">
          <h2>键盘快捷键</h2>
          <div class="help-keys">
            <div><kbd>1</kbd> 最近 · <kbd>2</kbd> 按日期 · <kbd>3</kbd> 按群 · <kbd>4</kbd> 矩阵 · <kbd>5</kbd> 搜索</div>
            <div><kbd>j</kbd> / <kbd>k</kbd> 上下移动　<kbd>g</kbd> / <kbd>G</kbd> 跳到首尾</div>
            <div><kbd>Enter</kbd> 进入光标项　<kbd>Esc</kbd> 返回</div>
            <div><kbd>/</kbd> 聚焦搜索　<kbd>?</kbd> 打开这张表</div>
          </div>
          <p class="help-foot">
            输入框里按 Esc 会先退出输入，不会离开页面。
          </p>
        </div>
      </div>`,
  };

  createApp(App).mount("#app");
})();
