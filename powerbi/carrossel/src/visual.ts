/*
 * Carrossel de linhas (radar-onibus-bh).
 *
 * Cartoes em coverflow 3D, um por linha, mais o cartao "Rede inteira" na frente.
 * O cartao do centro filtra a pagina por dim_linha[route_id] (applyJsonFilter);
 * a rede inteira tira o filtro. Gira com clique, setas, roda do mouse e teclado.
 * Sem bibliotecas: CSS 3D com transition e SVG montado a mao.
 */
"use strict";

import powerbi from "powerbi-visuals-api";
import "./../style/visual.less";

import VisualConstructorOptions = powerbi.extensibility.visual.VisualConstructorOptions;
import VisualUpdateOptions = powerbi.extensibility.visual.VisualUpdateOptions;
import IVisual = powerbi.extensibility.visual.IVisual;
import IVisualHost = powerbi.extensibility.visual.IVisualHost;
import IVisualEventService = powerbi.extensibility.IVisualEventService;
import DataView = powerbi.DataView;
import FilterAction = powerbi.FilterAction;

// Tamanho de desenho: o painel da Ficha no relatorio (1752 x 484). O visual escala por cima.
const BASE_W = 1752;
const BASE_H = 484;
const CARTAO_W = 480;
const VISIVEIS = 4; // cartoes de cada lado do centro
const ESPERA_FILTRO = 380; // ms parado antes de filtrar (giro rapido nao dispara consulta a cada passo)
const MAX_SUGESTOES = 6;

// Ordem dos cartoes (a rede inteira fica sempre na frente). Fica salva no visual (objeto "ordem").
type Ordem = "volume" | "maior" | "menor";
const ORDENS: { k: Ordem; rot: string; contador: string; dica: string }[] = [
    { k: "maior", rot: "Maior espera", contador: "PELA MAIOR ESPERA EXTRA", dica: "Da maior espera extra para a menor" },
    { k: "menor", rot: "Menor espera", contador: "PELA MENOR ESPERA EXTRA", dica: "Da menor espera extra para a maior" },
    { k: "volume", rot: "Peso na rede", contador: "PELO PESO NA REDE", dica: "Espera extra × horas de serviço: quem mais pesa na espera da rede" },
];
const ORDEM_PADRAO: Ordem = "maior";

const SVGNS = "http://www.w3.org/2000/svg";

interface Linha {
    id: string | number | null; // null = rede inteira
    nome: string;
    espera: number | null;
    extra: number | null;
    colados: number | null;
    corte: number | null;
    parte: number | null;
    posicao: number | null;
    volume: number;
    tendencia: (number | null)[];
}

interface Rede {
    espera: number | null;
    extra: number | null;
    colados: number | null;
    corte: number | null;
    linhas: number;
    ini: string;
    fim: string;
    tendencia: (number | null)[];
}

const fmt2 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fmt1 = new Intl.NumberFormat("pt-BR", { minimumFractionDigits: 1, maximumFractionDigits: 1 });
const fmt0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });

function num(v: unknown): number | null {
    if (v === null || v === undefined || v === "") return null;
    const n = Number(v);
    return isFinite(n) ? n : null;
}

function serie(texto: string): (number | null)[] {
    if (!texto) return [];
    return texto.split(";").map(s => num(s));
}

function el(tag: string, classe?: string, texto?: string): HTMLElement {
    const e = document.createElement(tag);
    if (classe) e.className = classe;
    if (texto !== undefined) e.textContent = texto;
    return e;
}

function sv(tag: string, attrs: Record<string, string | number>, pai?: Element): SVGElement {
    const e = document.createElementNS(SVGNS, tag);
    for (const k of Object.keys(attrs)) e.setAttribute(k, String(attrs[k]));
    if (pai) pai.appendChild(e);
    return e;
}

// Minusculo e sem acento: "Estação" e "estacao" batem na busca
function normal(s: string): string {
    return s.normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();
}

function minutos(v: number | null, sinal = false): string {
    if (v === null) return "–";
    return (sinal && v > 0 ? "+" : "") + fmt2.format(v);
}

function pct(v: number | null): string {
    return v === null ? "–" : fmt1.format(v * 100) + "%";
}

// Onibus de lado, em linhas finas. A cor vem de currentColor.
function onibus(): SVGElement {
    const s = sv("svg", { viewBox: "0 0 96 44", width: 96, height: 44, class: "bus" });
    sv("rect", { x: 3, y: 4, width: 88, height: 30, rx: 7, fill: "none", stroke: "currentColor", "stroke-width": 2.2 }, s);
    for (let i = 0; i < 5; i++) {
        sv("rect", { x: 9 + i * 14, y: 10, width: 10, height: 10, rx: 2, fill: "currentColor", "fill-opacity": 0.28 }, s);
    }
    sv("rect", { x: 79, y: 10, width: 8, height: 19, rx: 2, fill: "none", stroke: "currentColor", "stroke-width": 1.6 }, s);
    sv("line", { x1: 3, x2: 91, y1: 25, y2: 25, stroke: "currentColor", "stroke-width": 1.2, "stroke-opacity": 0.5 }, s);
    for (const cx of [22, 70]) {
        sv("circle", { cx, cy: 35, r: 6.5, fill: "#111729", stroke: "currentColor", "stroke-width": 2.2 }, s);
        sv("circle", { cx, cy: 35, r: 1.8, fill: "currentColor" }, s);
    }
    sv("line", { x1: 0, x2: 96, y1: 42.5, y2: 42.5, stroke: "currentColor", "stroke-width": 1, "stroke-dasharray": "6 5", "stroke-opacity": 0.45 }, s);
    return s;
}

export class Visual implements IVisual {
    private host: IVisualHost;
    private events: IVisualEventService;
    private raiz: HTMLElement;
    private elemento: HTMLElement;
    private palco: HTMLElement;
    private trilhaFill: HTMLElement;
    private contador: HTMLElement;
    private dica: HTMLElement;
    private vazio: HTMLElement;
    private caixaBusca: HTMLElement;
    private busca: HTMLInputElement;
    private sugestoes: HTMLElement;
    private achados: number[] = []; // indices em linhas, na ordem da lista de sugestoes
    private marcado = 0;
    private ordem: Ordem = ORDEM_PADRAO;
    private botoesOrdem = new Map<Ordem, HTMLElement>();

    private linhas: Linha[] = [];
    private rede: Rede | null = null;
    private centro = 0;
    private filtroAtual: string | number | null = null; // o que esta aplicado no host
    private alvo = { table: "dim_linha", column: "route_id" };
    private cartoes = new Map<string, HTMLElement>(); // chave da linha -> cartao no DOM
    private timerFiltro: number | undefined;
    private ultimaRoda = 0;
    private assinatura = "";

    constructor(options: VisualConstructorOptions) {
        this.host = options.host;
        this.events = options.host.eventService;

        const raiz = el("div", "carrossel");
        raiz.tabIndex = 0;
        this.raiz = raiz;

        const topo = el("div", "topo");
        this.dica = el("div", "dica", "clique num cartão · setas · roda do mouse");
        this.contador = el("div", "contador");

        this.palco = el("div", "palco");
        const chao = el("div", "chao");

        const esq = el("button", "seta esq");
        esq.setAttribute("aria-label", "Linha anterior");
        esq.appendChild(this.chevron(true));
        const dir = el("button", "seta dir");
        dir.setAttribute("aria-label", "Próxima linha");
        dir.appendChild(this.chevron(false));
        esq.addEventListener("click", e => { e.stopPropagation(); this.ir(this.centro - 1); });
        dir.addEventListener("click", e => { e.stopPropagation(); this.ir(this.centro + 1); });

        const trilha = el("div", "trilha");
        this.trilhaFill = el("div", "trilha-fill");
        trilha.appendChild(this.trilhaFill);
        topo.append(this.dica, this.contador, trilha);

        this.vazio = el("div", "vazio", "Sem linhas com espera medida no recorte");

        // Busca: numero ou nome da linha, lista de sugestoes, Enter gira ate o cartao
        this.caixaBusca = el("div", "busca");
        const barra = el("div", "busca-barra");
        const lupa = sv("svg", { viewBox: "0 0 24 24", width: 20, height: 20, class: "lupa" });
        sv("circle", { cx: 10.5, cy: 10.5, r: 6.5, fill: "none", stroke: "currentColor", "stroke-width": 2.2 }, lupa);
        sv("path", { d: "M15.5 15.5L21 21", stroke: "currentColor", "stroke-width": 2.4, "stroke-linecap": "round" }, lupa);
        this.busca = document.createElement("input");
        this.busca.type = "text";
        this.busca.className = "busca-campo";
        this.busca.placeholder = "buscar linha: número ou nome";
        this.busca.spellcheck = false;
        this.busca.autocomplete = "off";
        this.busca.setAttribute("aria-label", "Buscar linha pelo número ou pelo nome");
        const limpar = el("button", "busca-limpar");
        limpar.setAttribute("aria-label", "Limpar busca");
        const x = sv("svg", { viewBox: "0 0 24 24", width: 16, height: 16 });
        sv("path", { d: "M6 6l12 12M18 6L6 18", stroke: "currentColor", "stroke-width": 2.4, "stroke-linecap": "round" }, x);
        limpar.appendChild(x);
        barra.append(lupa, this.busca, limpar);
        this.sugestoes = el("div", "sugestoes");
        this.caixaBusca.append(barra, this.sugestoes);

        // Ordem: tres botoes a esquerda da busca
        const caixaOrdem = el("div", "ordem");
        caixaOrdem.appendChild(el("span", "ordem-rot", "ORDEM"));
        const grupo = el("div", "ordem-grupo");
        for (const o of ORDENS) {
            const b = el("button", "ordem-bt", o.rot);
            b.title = o.dica;
            b.addEventListener("mousedown", e => e.preventDefault()); // o foco fica no carrossel
            b.addEventListener("click", e => { e.stopPropagation(); this.trocarOrdem(o.k, true); });
            this.botoesOrdem.set(o.k, b);
            grupo.appendChild(b);
        }
        caixaOrdem.appendChild(grupo);
        caixaOrdem.addEventListener("wheel", e => e.stopPropagation());

        raiz.append(topo, chao, this.palco, esq, dir, this.vazio, caixaOrdem, this.caixaBusca);
        this.marcarOrdem();
        // titulo do painel: a arte desenha por baixo; so aparece no modo foco, quando a arte some
        const tituloFoco = el("div", "titulo-foco");
        tituloFoco.append(el("div", "tf-num", "01"), el("div", "tf-olho", "LINHAS"), el("div", "tf-tit", "Gire e escolha a linha"));
        raiz.insertBefore(tituloFoco, raiz.firstChild);
        options.element.appendChild(raiz);
        this.elemento = options.element;

        this.busca.addEventListener("input", () => this.filtrar());
        this.busca.addEventListener("focus", () => { if (this.busca.value.trim()) this.filtrar(); });
        this.busca.addEventListener("blur", () => this.fecharLista());
        this.busca.addEventListener("keydown", e => {
            e.stopPropagation(); // setas, Home e End ficam no campo, nao giram o carrossel
            const k = e.key;
            if (k === "ArrowDown" || k === "ArrowUp") {
                if (this.achados.length) this.marcar((this.marcado + (k === "ArrowDown" ? 1 : -1) + this.achados.length) % this.achados.length);
            } else if (k === "Enter") {
                this.escolher(this.marcado);
            } else if (k === "Escape") {
                if (this.busca.value) { this.busca.value = ""; this.filtrar(); } else this.raiz.focus();
            } else return;
            e.preventDefault();
        });
        limpar.addEventListener("mousedown", e => e.preventDefault());
        limpar.addEventListener("click", e => {
            e.stopPropagation();
            this.busca.value = "";
            this.filtrar();
            this.busca.focus();
        });
        this.caixaBusca.addEventListener("wheel", e => e.stopPropagation());
        // mousedown no lugar do clique: sem isso o campo perde o foco e a lista some antes do clique
        this.sugestoes.addEventListener("mousedown", e => e.preventDefault());

        raiz.addEventListener("wheel", e => {
            e.preventDefault();
            const agora = Date.now();
            if (agora - this.ultimaRoda < 160) return;
            this.ultimaRoda = agora;
            const d = Math.abs(e.deltaY) >= Math.abs(e.deltaX) ? e.deltaY : e.deltaX;
            if (d !== 0) this.ir(this.centro + (d > 0 ? 1 : -1));
        }, { passive: false });

        raiz.addEventListener("keydown", e => {
            const k = e.key;
            // comecar a digitar com o carrossel em foco ja vai para a busca (a letra cai no campo)
            if (k.length === 1 && k !== " " && !e.ctrlKey && !e.metaKey && !e.altKey) {
                this.busca.focus();
                return;
            }
            if (k === "ArrowRight" || k === "ArrowDown") this.ir(this.centro + 1);
            else if (k === "ArrowLeft" || k === "ArrowUp") this.ir(this.centro - 1);
            else if (k === "Home") this.ir(0);
            else if (k === "End") this.ir(this.linhas.length - 1);
            else return;
            e.preventDefault();
        });
    }

    private chevron(esquerda: boolean): SVGElement {
        const s = sv("svg", { viewBox: "0 0 24 24", width: 22, height: 22 });
        sv("path", { d: esquerda ? "M15 5l-7 7 7 7" : "M9 5l7 7-7 7", fill: "none", stroke: "currentColor",
            "stroke-width": 2.4, "stroke-linecap": "round", "stroke-linejoin": "round" }, s);
        return s;
    }

    // ------------------------------------------------------------------ dados
    public update(options: VisualUpdateOptions): void {
        this.events.renderingStarted(options);
        try {
            const vp = options.viewport;
            // modo foco: o visual aparece sem a arte do relatorio, entao pinta o proprio fundo
            const foco = !!(options as any).isInFocus;
            this.raiz.classList.toggle("foco", foco);
            this.elemento.style.background = foco ? "#0A0E1C" : "";
            const escala = Math.min(vp.width / BASE_W, vp.height / BASE_H);
            // zoom (e nao transform: scale) para o texto ser desenhado no tamanho final: com scale o
            // navegador rasteriza em 1752x484 e encolhe, e os cartoes 3D ficam borrados.
            // left/top do proprio elemento tambem passam pelo zoom, por isso a divisao.
            (this.raiz.style as any).zoom = String(escala);
            this.raiz.style.left = `${(vp.width - BASE_W * escala) / 2 / escala}px`;
            this.raiz.style.top = `${(vp.height - BASE_H * escala) / 2 / escala}px`;

            const dv = options.dataViews && options.dataViews[0];
            const objs = (dv && dv.metadata && dv.metadata.objects) as any;
            const salva = objs && objs.ordem && objs.ordem.modo;
            const ordemSalva: Ordem = ORDENS.some(o => o.k === salva) ? salva : ORDEM_PADRAO;
            if (ordemSalva !== this.ordem) { this.ordem = ordemSalva; this.marcarOrdem(); }
            const mudouDado = this.ler(dv);

            // Filtro salvo no visual (o que o host lembra)
            let salvo: string | number | null = null;
            const filtros = (options.jsonFilters || []) as any[];
            for (const f of filtros) {
                if (f && f.target && f.target.column === this.alvo.column && Array.isArray(f.values) && f.values.length) {
                    salvo = f.values[0];
                }
            }
            this.filtroAtual = salvo;

            if (mudouDado || this.cartoes.size === 0) {
                let idx = 0;
                if (salvo !== null) {
                    idx = this.linhas.findIndex(l => l.id !== null && String(l.id) === String(salvo));
                    if (idx < 0) {
                        // a linha escolhida saiu do recorte (filtro LINHA do cabecalho, periodo): volta para a rede
                        idx = 0;
                        this.aplicarFiltro(null);
                    }
                }
                this.centro = idx;
                this.limparCartoes();
            } else if (salvo !== null) {
                const idx = this.linhas.findIndex(l => l.id !== null && String(l.id) === String(salvo));
                if (idx >= 0 && idx !== this.centro && this.timerFiltro === undefined) this.centro = idx;
            }
            this.render(true);
            // dado novo com a lista aberta: os indices das sugestoes mudaram
            if (mudouDado && this.sugestoes.classList.contains("aberta")) this.filtrar();
            this.events.renderingFinished(options);
        } catch (erro) {
            this.events.renderingFailed(options, String(erro));
        }
    }

    // Le o dataView. Devolve true se as linhas ou os numeros mudaram.
    private ler(dv: DataView | undefined): boolean {
        const cat = dv && dv.categorical && dv.categorical.categories && dv.categorical.categories[0];
        const linhas: Linha[] = [];
        let rede: Rede | null = null;
        if (cat) {
            const qn = cat.source.queryName || "";
            const ponto = qn.indexOf(".");
            if (ponto > 0) this.alvo = { table: qn.slice(0, ponto), column: qn.slice(ponto + 1) };
            const cols: Record<string, powerbi.PrimitiveValue[]> = {};
            for (const v of dv.categorical.values || []) {
                const roles = v.source.roles || {};
                for (const r of Object.keys(roles)) if (roles[r]) cols[r] = v.values;
            }
            const pega = (r: string, i: number) => (cols[r] ? cols[r][i] : null);
            let textoRede = "";
            for (let i = 0; i < cat.values.length; i++) {
                const id = cat.values[i] as string | number;
                if (id === null || id === undefined) continue;
                if (num(pega("volume", i)) === null) continue; // fora do ranking, como em [Linhas na rede]
                if (!textoRede && pega("rede", i)) textoRede = String(pega("rede", i));
                linhas.push({
                    id,
                    nome: String(pega("nome", i) ?? ""),
                    espera: num(pega("espera", i)),
                    extra: num(pega("extra", i)),
                    colados: num(pega("colados", i)),
                    corte: num(pega("corte", i)),
                    parte: num(pega("parte", i)),
                    posicao: num(pega("posicao", i)),
                    volume: num(pega("volume", i)) as number,
                    tendencia: serie(String(pega("tendencia", i) ?? "")),
                });
            }
            if (textoRede) {
                const [numeros, tend] = textoRede.split("|");
                const p = numeros.split(";");
                rede = {
                    espera: num(p[0]), extra: num(p[1]), colados: num(p[2]), corte: num(p[3]),
                    linhas: num(p[4]) ?? linhas.length, ini: p[5] || "", fim: p[6] || "",
                    tendencia: serie(tend || ""),
                };
            }
        }
        this.ordenar(linhas);
        if (rede) {
            linhas.unshift({
                id: null, nome: "Todas as linhas medidas no recorte",
                espera: rede.espera, extra: rede.extra, colados: rede.colados, corte: rede.corte,
                parte: 1, posicao: null, volume: Infinity, tendencia: rede.tendencia,
            });
        }
        const assinatura = this.assinar(linhas, rede);
        const mudou = assinatura !== this.assinatura;
        this.assinatura = assinatura;
        this.linhas = linhas;
        this.rede = rede;
        return mudou;
    }

    private assinar(linhas: Linha[], rede: Rede | null): string {
        return JSON.stringify([this.ordem, linhas.map(l => [l.id, l.extra, l.espera, l.colados, l.parte]), rede]);
    }

    // Ordena so as linhas (sem a rede). Linha sem espera extra vai para o fim; empate pelo volume.
    private ordenar(linhas: Linha[]): void {
        const o = this.ordem;
        linhas.sort((a, b) => {
            if (o !== "volume") {
                if (a.extra === null || b.extra === null) {
                    if (a.extra !== b.extra) return a.extra === null ? 1 : -1;
                } else if (a.extra !== b.extra) {
                    return o === "maior" ? b.extra - a.extra : a.extra - b.extra;
                }
            }
            return b.volume - a.volume;
        });
    }

    // Troca a ordem mantendo no centro a linha que esta la (o filtro da pagina nao muda)
    private trocarOrdem(o: Ordem, salvar: boolean): void {
        if (o === this.ordem) return;
        const atual = this.linhas[this.centro];
        this.ordem = o;
        this.marcarOrdem();
        const corpo = this.linhas.filter(l => l.id !== null);
        this.ordenar(corpo);
        this.linhas = this.rede && this.linhas.length && this.linhas[0].id === null ? [this.linhas[0], ...corpo] : corpo;
        this.assinatura = this.assinar(this.linhas, this.rede); // o update que vem do persist nao reconstroi
        const idx = atual ? this.linhas.indexOf(atual) : 0;
        this.centro = idx >= 0 ? idx : 0;
        this.limparCartoes();
        this.render(true);
        if (this.sugestoes.classList.contains("aberta")) this.filtrar();
        if (salvar) {
            this.host.persistProperties({ merge: [{ objectName: "ordem", selector: null as any, properties: { modo: o } }] });
        }
    }

    private marcarOrdem(): void {
        this.botoesOrdem.forEach((b, k) => {
            b.classList.toggle("ligado", k === this.ordem);
            b.setAttribute("aria-pressed", k === this.ordem ? "true" : "false");
        });
    }

    // ------------------------------------------------------------------ giro e filtro
    private ir(i: number): void {
        const n = this.linhas.length;
        if (!n) return;
        const novo = Math.max(0, Math.min(n - 1, i));
        if (novo === this.centro) return;
        this.centro = novo;
        this.render(false);
        if (this.timerFiltro !== undefined) window.clearTimeout(this.timerFiltro);
        this.timerFiltro = window.setTimeout(() => {
            this.timerFiltro = undefined;
            const l = this.linhas[this.centro];
            if (l) this.aplicarFiltro(l.id);
        }, ESPERA_FILTRO);
    }

    private aplicarFiltro(id: string | number | null): void {
        if (id === null) {
            if (this.filtroAtual === null) return;
            this.filtroAtual = null;
            this.host.applyJsonFilter(null, "general", "filter", FilterAction.remove);
            return;
        }
        if (this.filtroAtual !== null && String(this.filtroAtual) === String(id)) return;
        this.filtroAtual = id;
        const filtro = {
            $schema: "http://powerbi.com/product/schema#basic",
            target: { table: this.alvo.table, column: this.alvo.column },
            filterType: 1,
            operator: "In",
            values: [id],
            requireSingleSelection: true,
        };
        this.host.applyJsonFilter(filtro as any, "general", "filter", FilterAction.merge);
    }

    // ------------------------------------------------------------------ busca
    // Ordem: numero exato, numero que comeca com o texto, palavra do nome que comeca com o texto,
    // texto no meio do nome, texto no meio do numero. Empate fica na ordem do carrossel.
    private filtrar(): void {
        const bruto = this.busca.value.trim();
        const q = normal(bruto);
        this.caixaBusca.classList.toggle("com-texto", this.busca.value.length > 0);
        if (!q) {
            this.achados = [];
            this.fecharLista();
            return;
        }
        const qPal = q.replace(/[^a-z0-9]+/g, " ").trim();
        const res: { i: number; p: number }[] = [];
        this.linhas.forEach((l, i) => {
            let p = -1;
            if (l.id === null) {
                if ("rede inteira todas as linhas".indexOf(q) >= 0) p = 5;
            } else {
                const id = normal(String(l.id));
                const nome = normal(l.nome);
                const palavras = " " + nome.replace(/[^a-z0-9]+/g, " ");
                if (id === q) p = 0;
                else if (id.startsWith(q)) p = 1;
                else if (qPal && palavras.indexOf(" " + qPal) >= 0) p = 2;
                else if (nome.indexOf(q) >= 0) p = 3;
                else if (id.indexOf(q) >= 0) p = 4;
            }
            if (p >= 0) res.push({ i, p });
        });
        res.sort((a, b) => a.p - b.p || a.i - b.i);
        this.achados = res.slice(0, MAX_SUGESTOES).map(r => r.i);
        this.marcado = 0;

        const lista = this.sugestoes;
        lista.textContent = "";
        if (!res.length) {
            lista.appendChild(el("div", "sug-nada", `Nenhuma linha com "${bruto}"`));
        }
        this.achados.forEach((i, k) => {
            const l = this.linhas[i];
            const ehRede = l.id === null;
            const item = el("div", "sug" + (k === 0 ? " marcado" : ""));
            item.appendChild(el("span", "sug-chip" + (ehRede ? " rede" : ""), ehRede ? "REDE" : String(l.id)));
            item.appendChild(this.realce(ehRede ? "Rede inteira" : l.nome || "Sem nome", q));
            item.appendChild(el("span", "sug-val", minutos(l.extra, true) + " min"));
            item.addEventListener("mouseenter", () => this.marcar(k));
            item.addEventListener("click", e => { e.stopPropagation(); this.escolher(k); });
            lista.appendChild(item);
        });
        if (res.length > MAX_SUGESTOES) {
            lista.appendChild(el("div", "sug-mais", `mais ${fmt0.format(res.length - MAX_SUGESTOES)}: continue digitando`));
        }
        lista.classList.add("aberta");
    }

    // Nome com o trecho buscado em destaque (comparacao sem acento, texto original na tela)
    private realce(nome: string, q: string): HTMLElement {
        const e = el("span", "sug-nome");
        const letras = Array.from(nome);
        const norm = letras.map(c => normal(c));
        if (norm.every(n => n.length === 1)) {
            const ini = norm.join("").indexOf(q);
            if (ini >= 0) {
                e.append(letras.slice(0, ini).join(""), el("b", "", letras.slice(ini, ini + q.length).join("")),
                    letras.slice(ini + q.length).join(""));
                return e;
            }
        }
        e.textContent = nome;
        return e;
    }

    private marcar(k: number): void {
        this.marcado = k;
        Array.from(this.sugestoes.querySelectorAll(".sug")).forEach((s, j) => s.classList.toggle("marcado", j === k));
    }

    private escolher(k: number): void {
        const i = this.achados[k];
        if (i === undefined) return;
        this.busca.value = "";
        this.caixaBusca.classList.remove("com-texto");
        this.achados = [];
        this.fecharLista();
        this.raiz.focus(); // setas e roda voltam a girar o carrossel
        this.ir(i);
    }

    private fecharLista(): void {
        this.sugestoes.classList.remove("aberta");
    }

    // ------------------------------------------------------------------ desenho
    private chave(l: Linha): string {
        return l.id === null ? "__rede__" : "l:" + String(l.id);
    }

    private limparCartoes(): void {
        this.cartoes.forEach(c => c.remove());
        this.cartoes.clear();
    }

    private posicionar(c: HTMLElement, d: number): void {
        const a = Math.abs(d);
        const s = Math.sign(d);
        const x = a === 0 ? 0 : s * (500 + (a - 1) * 170);
        const z = -a * 150;
        const rot = -s * Math.min(a, 2) * 22;
        const escala = a === 0 ? 1 : Math.max(0.62, 0.86 - (a - 1) * 0.08);
        // Cada cartao de lado leva o proprio perspective() (o palco nao e contexto 3D): o do centro fica
        // sem transform nenhum, fora de camada de composicao, e o texto sai nitido no tamanho final.
        c.style.transform = a === 0 ? "none"
            : `perspective(1500px) translate3d(${x}px, 0, ${z}px) rotateY(${rot}deg) scale(${escala})`;
        c.style.zIndex = String(100 - a);
        c.style.opacity = a > VISIVEIS ? "0" : String(Math.max(0.25, 1 - a * 0.17));
        c.style.pointerEvents = a > VISIVEIS ? "none" : "auto";
        c.classList.toggle("ativo", a === 0);
    }

    private render(instantaneo: boolean): void {
        const n = this.linhas.length;
        this.vazio.style.display = n ? "none" : "flex";
        this.raiz.classList.toggle("sem-dados", !n);
        if (!n) {
            this.limparCartoes();
            this.contador.textContent = "";
            this.trilhaFill.style.width = "0";
            return;
        }
        if (this.centro >= n) this.centro = n - 1;

        const queremos = new Set<string>();
        for (let d = -VISIVEIS - 1; d <= VISIVEIS + 1; d++) {
            const i = this.centro + d;
            if (i < 0 || i >= n) continue;
            const l = this.linhas[i];
            const k = this.chave(l);
            queremos.add(k);
            let c = this.cartoes.get(k);
            const novo = !c;
            if (!c) {
                c = this.cartao(l, i);
                this.cartoes.set(k, c);
                // nasce na ponta, ja na posicao de fora, para entrar deslizando
                c.style.transition = "none";
                this.posicionar(c, d < 0 ? d - 1 : d + 1);
                if (Math.abs(d) <= VISIVEIS) c.style.opacity = "0";
                this.palco.appendChild(c);
            }
            if (instantaneo && novo) {
                this.posicionar(c, d);
            } else {
                // forca o navegador a registrar a posicao inicial antes da transicao
                void c.offsetWidth;
                c.style.transition = "";
                this.posicionar(c, d);
            }
            if (instantaneo && novo) {
                void c.offsetWidth;
                c.style.transition = "";
            }
            const eraAtivo = c.dataset.ativo === "1";
            c.dataset.ativo = d === 0 ? "1" : "0";
            if (d === 0 && !eraAtivo) this.animarEntrada(c);
            const idx = i;
            c.onclick = () => this.ir(idx);
        }
        this.cartoes.forEach((c, k) => {
            if (!queremos.has(k)) {
                c.remove();
                this.cartoes.delete(k);
            }
        });

        const l = this.linhas[this.centro];
        const total = this.rede ? n - 1 : n;
        this.contador.textContent = l.id === null
            ? `REDE INTEIRA · ${fmt0.format(total)} LINHAS`
            : `${fmt0.format(this.rede ? this.centro : this.centro + 1)} DE ${fmt0.format(total)} ${(ORDENS.find(o => o.k === this.ordem) || ORDENS[0]).contador}`;
        this.trilhaFill.style.width = `${n > 1 ? (this.centro / (n - 1)) * 100 : 100}%`;
    }

    private cartao(l: Linha, i: number): HTMLElement {
        const ehRede = l.id === null;
        const c = el("div", "cartao" + (ehRede ? " rede" : ""));
        c.dataset.i = String(i);

        // topo: chip e posicao
        const topo = el("div", "c-topo");
        topo.appendChild(el("div", "chip", ehRede ? "REDE INTEIRA" : "LINHA " + String(l.id)));
        const total = this.rede ? this.rede.linhas : this.linhas.length;
        const pos = ehRede
            ? `${fmt0.format(total)} linhas`
            : l.posicao !== null ? `${fmt0.format(l.posicao)}ª de ${fmt0.format(total)} no peso` : "";
        topo.appendChild(el("div", "pos", pos));
        c.appendChild(topo);

        // identidade: onibus e nome
        const ident = el("div", "c-ident");
        ident.appendChild(onibus());
        ident.appendChild(el("div", "nome", l.nome || "Sem nome"));
        c.appendChild(ident);

        // meio: espera extra grande e anel da parte da rede
        const meio = el("div", "c-meio");
        const grande = el("div", "grande");
        grande.appendChild(el("div", "rot", "ESPERA EXTRA POR IDA AO PONTO"));
        const linhaValor = el("div", "valor-linha");
        const valor = el("span", "valor", minutos(l.extra, true));
        if (l.extra !== null) { valor.dataset.alvo = String(l.extra); valor.dataset.tipo = "min+"; }
        linhaValor.append(valor, el("span", "un", "min"));
        grande.appendChild(linhaValor);
        if (!ehRede && this.rede && this.rede.extra !== null && l.extra !== null) {
            const dif = l.extra - this.rede.extra;
            const acima = dif > 0.005;
            const abaixo = dif < -0.005;
            const t = acima ? `▲ ${fmt2.format(dif)} acima da rede` : abaixo ? `▼ ${fmt2.format(-dif)} abaixo da rede` : "igual à rede";
            grande.appendChild(el("div", "comp " + (acima ? "pior" : abaixo ? "melhor" : ""), t));
        } else if (ehRede) {
            grande.appendChild(el("div", "comp", "média de todas as linhas"));
        }
        meio.appendChild(grande);
        meio.appendChild(this.anel(l.parte, ehRede));
        c.appendChild(meio);

        // tres numeros pequenos
        const mini = el("div", "c-mini");
        const item = (rot: string, v: string, cls: string, alvo: number | null, tipo: string) => {
            const b = el("div", "m " + cls);
            b.appendChild(el("div", "m-rot", rot));
            const s = el("div", "m-val", v);
            if (alvo !== null) { s.dataset.alvo = String(alvo); s.dataset.tipo = tipo; }
            b.appendChild(s);
            mini.appendChild(b);
        };
        item("ESPERA MÉDIA", minutos(l.espera) + " min", "azul", l.espera, "min");
        item("COLADOS", pct(l.colados), "vermelho", l.colados, "pct");
        item("CORTE SEM COLAGEM", pct(l.corte), "verde", l.corte, "pct");
        c.appendChild(mini);

        // sparkline da espera extra por dia
        c.appendChild(this.sparkline(l, ehRede));
        return c;
    }

    private anel(parte: number | null, ehRede: boolean): HTMLElement {
        const caixa = el("div", "anel");
        const r = 34;
        const circ = 2 * Math.PI * r;
        const s = sv("svg", { viewBox: "-4 -4 88 88", width: 88, height: 88 });
        sv("circle", { cx: 40, cy: 40, r, fill: "none", stroke: "#2A3456", "stroke-width": 8 }, s);
        const v = Math.max(0, Math.min(1, parte ?? 0));
        // parte pequena ainda aparece: o arco minimo e de 2%
        const vis = v > 0 ? Math.max(v, 0.02) : 0;
        const arco = sv("circle", {
            cx: 40, cy: 40, r, fill: "none", stroke: "#FFB347", "stroke-width": 8, "stroke-linecap": "round",
            "stroke-dasharray": `${circ * vis} ${circ}`, transform: "rotate(-90 40 40)", class: "arco",
        }, s);
        arco.style.setProperty("--circ", String(circ));
        caixa.appendChild(s);
        const centro = el("div", "anel-centro");
        const val = el("div", "anel-val", ehRede ? "100%" : pct(parte));
        if (!ehRede && parte !== null) { val.dataset.alvo = String(parte); val.dataset.tipo = "pct"; }
        centro.appendChild(val);
        caixa.appendChild(centro);
        caixa.appendChild(el("div", "anel-rot", ehRede ? "da espera extra" : "da espera extra da rede"));
        return caixa;
    }

    private sparkline(l: Linha, ehRede: boolean): HTMLElement {
        const caixa = el("div", "c-spark");
        const W = 452, H = 42;
        const s = sv("svg", { viewBox: `0 0 ${W} ${H}`, width: W, height: H });
        const vals = l.tendencia;
        const redeVals = this.rede ? this.rede.tendencia : [];
        const todos = vals.concat(ehRede ? [] : redeVals).filter((v): v is number => v !== null);
        const n = vals.length;
        if (n >= 2 && todos.length) {
            const topo = Math.max(...todos) * 1.1 || 1;
            const x = (i: number) => 4 + (i / (n - 1)) * (W - 8);
            const y = (v: number) => H - 4 - (v / topo) * (H - 10);
            const caminho = (serieV: (number | null)[]) => {
                let d = "";
                let caneta = false;
                serieV.forEach((v, i) => {
                    if (v === null) { caneta = false; return; }
                    d += `${caneta ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`;
                    caneta = true;
                });
                return d;
            };
            if (!ehRede && redeVals.length === n) {
                sv("path", { d: caminho(redeVals), fill: "none", stroke: "#9AA3C2", "stroke-width": 1.4,
                    "stroke-dasharray": "3 4", "stroke-opacity": 0.8 }, s);
            }
            const area = caminho(vals);
            const primeiro = vals.findIndex(v => v !== null);
            let ultimo = -1;
            vals.forEach((v, i) => { if (v !== null) ultimo = i; });
            if (primeiro >= 0 && ultimo > primeiro) {
                const defs = sv("defs", {}, s);
                const g = sv("linearGradient", { id: `g${Math.random().toString(36).slice(2, 8)}`, x1: 0, x2: 0, y1: 0, y2: 1 }, defs);
                sv("stop", { offset: "0", "stop-color": "#FFB347", "stop-opacity": 0.32 }, g);
                sv("stop", { offset: "1", "stop-color": "#FFB347", "stop-opacity": 0 }, g);
                // area so no trecho continuo inteiro (simplificacao: liga os buracos)
                const pts = vals.map((v, i) => (v === null ? null : `${x(i).toFixed(1)},${y(v).toFixed(1)}`)).filter(Boolean);
                sv("path", { d: `M${x(primeiro).toFixed(1)},${H} L${pts.join(" L")} L${x(ultimo).toFixed(1)},${H} Z`,
                    fill: `url(#${g.getAttribute("id")})`, class: "spark-area" }, s);
            }
            const linha = sv("path", { d: area, fill: "none", stroke: "#FFB347", "stroke-width": 2.4,
                "stroke-linejoin": "round", "stroke-linecap": "round", class: "spark-linha", pathLength: 1 }, s);
            linha.setAttribute("pathLength", "1");
            if (ultimo >= 0) {
                sv("circle", { cx: x(ultimo), cy: y(vals[ultimo] as number), r: 3.6, fill: "#FFB347", class: "spark-ponto" }, s);
            }
        }
        caixa.appendChild(s);
        const leg = el("div", "spark-leg");
        leg.appendChild(el("span", "", this.rede ? this.rede.ini : ""));
        leg.appendChild(el("span", "spark-meio", ehRede ? "espera extra por dia" : "por dia · tracejado: a rede"));
        leg.appendChild(el("span", "", this.rede ? this.rede.fim : ""));
        caixa.appendChild(leg);
        return caixa;
    }

    // Contagem dos numeros e linha desenhando, quando o cartao chega ao centro
    private animarEntrada(c: HTMLElement): void {
        c.classList.remove("entrando");
        void c.offsetWidth;
        c.classList.add("entrando");
        const alvos = Array.from(c.querySelectorAll<HTMLElement>("[data-alvo]"));
        const ini = performance.now();
        const dur = 750;
        const passo = (t: number) => {
            const k = Math.min(1, (t - ini) / dur);
            const e = 1 - Math.pow(1 - k, 3);
            for (const a of alvos) {
                const v = Number(a.dataset.alvo) * e;
                const tipo = a.dataset.tipo;
                if (tipo === "pct") a.textContent = pct(v);
                else if (tipo === "min") a.textContent = fmt2.format(v) + " min";
                else a.textContent = minutos(v, true);
            }
            if (k < 1 && c.isConnected) requestAnimationFrame(passo);
        };
        requestAnimationFrame(passo);
    }
}
