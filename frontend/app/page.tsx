"use client";

import { ChangeEvent, FormEvent, useEffect, useState } from "react";
import IcpEditor from "./IcpEditor";
import "./profile.css";
import "./documents.css";

const API = process.env.NEXT_PUBLIC_API_URL || "";
type Offer = { id?: string; name: string; category: "software" | "service" | "other"; description: string; problem_solved: string; differentiators: string; target_customer_hint: string; restrictions: string };
type ProfileResult = { generated_with: string; profile: Record<string, unknown>; evidence: { filename: string; content: string; relevance: number }[] };
const emptyOffer: Offer = { name: "", category: "software", description: "", problem_solved: "", differentiators: "", target_customer_hint: "", restrictions: "" };

async function request(path: string, token: string, init?: RequestInit) {
  const response = await fetch(`${API}${path}`, { ...init, headers: { ...(init?.headers || {}), Authorization: `Bearer ${token}` } });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "Não foi possível concluir a operação.");
  }
  return response.json();
}

export default function Home() {
  const [token, setToken] = useState("");
  const [mode, setMode] = useState<"register" | "login">("register");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [companyName, setCompanyName] = useState("");
  const [website, setWebsite] = useState("");
  const [companyDescription, setCompanyDescription] = useState("");
  const [salesRegions, setSalesRegions] = useState("");
  const [offers, setOffers] = useState<Offer[]>([{ ...emptyOffer }]);
  const [selectedOffer, setSelectedOffer] = useState("");
  const [documents, setDocuments] = useState<{ id: string; filename: string; status: string }[]>([]);
  const [profile, setProfile] = useState<ProfileResult | null>(null);
  const [profileDraft, setProfileDraft] = useState("");
  const [profileStatus, setProfileStatus] = useState("draft");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { const saved = window.localStorage.getItem("le360_token"); if (saved) setToken(saved); }, []);
  useEffect(() => {
    if (!token) return;
    request("/api/v1/onboarding", token).then((data) => {
      if (!data) return;
      setCompanyName(data.name || ""); setWebsite(data.website || ""); setCompanyDescription(data.description || ""); setSalesRegions(data.sales_regions || "");
      const loaded = data.offers?.length ? data.offers.map((offer: Offer) => ({ ...emptyOffer, ...offer })) : [{ ...emptyOffer }];
      setOffers(loaded); setSelectedOffer(loaded[0]?.id || "");
    }).catch((error) => setNotice(error.message));
  }, [token]);

  async function authenticate(event: FormEvent) {
    event.preventDefault(); setBusy(true); setNotice("");
    try {
      const path = mode === "register" ? "/api/v1/auth/register" : "/api/v1/auth/login";
      const payload = mode === "register" ? { company_name: companyName, email, password } : { email, password };
      const response = await fetch(`${API}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      const data = await response.json(); if (!response.ok) throw new Error(data.detail || "Não foi possível entrar.");
      window.localStorage.setItem("le360_token", data.access_token); setToken(data.access_token); setNotice("Acesso criado. Complete o perfil da sua empresa e da oferta.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Falha de conexão."); }
    finally { setBusy(false); }
  }

  async function saveOnboarding(event: FormEvent) {
    event.preventDefault(); setBusy(true); setNotice("");
    try {
      const result = await request("/api/v1/onboarding", token, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ company_name: companyName, website, company_description: companyDescription, sales_regions: salesRegions, offers }) });
      const loaded = result.offers.map((offer: Offer) => ({ ...emptyOffer, ...offer }));
      setOffers(loaded); setSelectedOffer((current) => loaded.some((offer: Offer) => offer.id === current) ? current : loaded[0]?.id || "");
      setNotice("Perfil comercial salvo.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Falha ao salvar."); }
    finally { setBusy(false); }
  }

  async function loadDocuments(offerId: string) {
    if (!offerId || !token) return;
    try {
      setDocuments(await request(`/api/v1/offers/${offerId}/documents`, token));
      const saved = await request(`/api/v1/offers/${offerId}/icp`, token);
      if (saved) { setProfile({ generated_with: saved.generated_with, profile: saved.profile, evidence: saved.evidence || [] }); setProfileDraft(JSON.stringify(saved.profile, null, 2)); setProfileStatus(saved.status); }
    }
    catch (error) { setNotice(error instanceof Error ? error.message : "Falha ao carregar documentos."); }
  }
  useEffect(() => { loadDocuments(selectedOffer); setProfile(null); }, [selectedOffer, token]);
  useEffect(() => {
    if (!selectedOffer || !documents.some((doc) => doc.status === "queued" || doc.status === "indexing")) return;
    const timer = window.setInterval(() => loadDocuments(selectedOffer), 3000);
    return () => window.clearInterval(timer);
  }, [selectedOffer, token, documents]);

  async function upload(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0]; if (!file || !selectedOffer) return;
    setBusy(true); setNotice("");
    try {
      const body = new FormData(); body.append("file", file);
      await request(`/api/v1/offers/${selectedOffer}/documents`, token, { method: "POST", body });
      await loadDocuments(selectedOffer); setNotice("Documento enviado para indexação. A geração do ICP será liberada quando o processamento terminar.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Falha no envio."); }
    finally { setBusy(false); event.target.value = ""; }
  }

  async function generateProfile() {
    setBusy(true); setNotice("");
    try { const result = await request(`/api/v1/offers/${selectedOffer}/profile`, token, { method: "POST" }); setProfile(result); setProfileDraft(JSON.stringify(result.profile, null, 2)); setProfileStatus("draft"); setNotice("Perfil gerado. Revise as hipóteses antes de usá-las na prospecção."); }
    catch (error) { setNotice(error instanceof Error ? error.message : "Falha ao gerar perfil."); }
    finally { setBusy(false); }
  }

  async function saveProfile(status: "draft" | "approved") {
    if (!selectedOffer) return;
    setBusy(true); setNotice("");
    try {
      const parsed = JSON.parse(profileDraft);
      const saved = await request(`/api/v1/offers/${selectedOffer}/icp`, token, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ profile: parsed, status }) });
      setProfile({ generated_with: saved.generated_with, profile: saved.profile, evidence: saved.evidence || [] }); setProfileDraft(JSON.stringify(saved.profile, null, 2)); setProfileStatus(saved.status);
      setNotice(status === "approved" ? "ICP revisado e aprovado para esta oferta." : "Rascunho do ICP salvo.");
    } catch (error) { setNotice(error instanceof SyntaxError ? "O JSON editado está inválido." : error instanceof Error ? error.message : "Não foi possível salvar o ICP."); }
    finally { setBusy(false); }
  }

  if (!token) return <main className="auth-layout"><section className="auth-art"><div className="brand"><span className="brand-mark">L</span> LeadEngine<span>360</span></div><div className="auth-message"><span className="eyebrow">INTELIGÊNCIA COMERCIAL B2B</span><h1>Comece pela sua oferta. Encontre quem precisa dela.</h1><p>Cadastre o que sua empresa vende, reúna seu conhecimento e prepare a base para descobrir oportunidades com contexto.</p></div><div className="auth-foot">Seu conhecimento comercial, pronto para encontrar novos caminhos.</div></section><section className="auth-panel"><form className="auth-card" onSubmit={authenticate}><div className="mobile-brand brand"><span className="brand-mark">L</span> LeadEngine<span>360</span></div><span className="eyebrow">PRIMEIRO PASSO</span><h2>{mode === "register" ? "Crie seu espaço" : "Bem-vindo de volta"}</h2><p className="muted">{mode === "register" ? "Vamos preparar o perfil comercial da sua empresa." : "Entre para continuar configurando suas ofertas."}</p>{mode === "register" && <label>Nome da empresa<input required value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Ex.: Acme Tecnologia" /></label>}<label>E-mail corporativo<input required type="email" value={email} onChange={(e) => setEmail(e.target.value)} placeholder="voce@empresa.com" /></label><label>Senha<input required minLength={10} type="password" value={password} onChange={(e) => setPassword(e.target.value)} placeholder="Pelo menos 10 caracteres" /></label>{notice && <div className="notice">{notice}</div>}<button className="primary full" disabled={busy}>{busy ? "Aguarde…" : mode === "register" ? "Criar espaço" : "Entrar"}<span>→</span></button><button type="button" className="text-button" onClick={() => { setMode(mode === "register" ? "login" : "register"); setNotice(""); }}>{mode === "register" ? "Já tem uma conta? Entrar" : "Ainda não tem conta? Criar espaço"}</button></form></section></main>;

  const activeOffer = offers.find((offer) => offer.id === selectedOffer) || offers[0];
  return <main className="workspace"><aside className="sidebar"><div className="brand"><span className="brand-mark">L</span> LeadEngine<span>360</span></div><div className="side-label">CONFIGURAÇÃO</div><div className="nav-item active"><span>01</span> Empresa e oferta</div><div className="nav-item disabled"><span>02</span> Perfil de cliente ideal</div><div className="nav-item disabled"><span>03</span> Oportunidades</div><div className="sidebar-bottom"><div className="avatar">{email.slice(0, 1).toUpperCase()}</div><div><b>{email}</b><small>Espaço da empresa</small></div><button title="Sair" className="logout" onClick={() => { window.localStorage.removeItem("le360_token"); setToken(""); }}>↗</button></div></aside>
    <section className="main-area"><header className="topbar"><div><span className="crumb">CONFIGURAÇÃO INICIAL</span><h1>Conte ao sistema o que você vende</h1></div><span className="step-pill">ETAPA 1 DE 3</span><a className="secondary" href="/team">Equipe</a><a className="secondary" href="/accounts">Ver contas →</a></header><div className="content"><div className="intro"><div className="intro-icon">✳</div><div><h2>Vamos construir seu contexto comercial</h2><p>As informações e os materiais da sua empresa ajudam o sistema a sugerir quem pode se beneficiar da sua oferta.</p></div></div>
      <form onSubmit={saveOnboarding} className="form-stack"><section className="card"><div className="card-heading"><span className="section-number">01</span><div><h3>Sua empresa</h3><p>Informações básicas sobre quem oferece a solução.</p></div></div><div className="fields two"><label>Nome da empresa<input required value={companyName} onChange={(e) => setCompanyName(e.target.value)} placeholder="Ex.: Acme Tecnologia" /></label><label>Site da empresa<input value={website} onChange={(e) => setWebsite(e.target.value)} placeholder="https://suaempresa.com.br" /></label><label className="wide">O que sua empresa faz?<textarea rows={3} value={companyDescription} onChange={(e) => setCompanyDescription(e.target.value)} placeholder="Descreva a empresa e sua experiência de mercado." /></label><label className="wide">Regiões atendidas<input value={salesRegions} onChange={(e) => setSalesRegions(e.target.value)} placeholder="Ex.: Brasil, América Latina" /></label></div></section>
      <section className="card"><div className="card-heading"><span className="section-number">02</span><div><h3>O que você vende</h3><p>Comece com uma oferta. Você poderá adicionar outras depois.</p></div></div>{offers.map((offer, index) => <div className="offer-block" key={offer.id || index}><div className="fields two"><label>Nome da oferta<input required value={offer.name} onChange={(e) => setOffers(offers.map((item, i) => i === index ? { ...item, name: e.target.value } : item))} placeholder="Ex.: Plataforma de gestão financeira" /></label><label>Tipo<select value={offer.category} onChange={(e) => setOffers(offers.map((item, i) => i === index ? { ...item, category: e.target.value as Offer["category"] } : item))}><option value="software">Software</option><option value="service">Serviço</option><option value="other">Outro</option></select></label><label className="wide">Descreva o produto ou serviço<textarea required minLength={10} rows={3} value={offer.description} onChange={(e) => setOffers(offers.map((item, i) => i === index ? { ...item, description: e.target.value } : item))} placeholder="O que faz, como funciona e qual resultado entrega?" /></label><label className="wide">Qual problema resolve?<textarea rows={2} value={offer.problem_solved} onChange={(e) => setOffers(offers.map((item, i) => i === index ? { ...item, problem_solved: e.target.value } : item))} placeholder="Que dificuldade leva um cliente a procurar essa solução?" /></label><label>Quem costuma comprar?<textarea rows={2} value={offer.target_customer_hint} onChange={(e) => setOffers(offers.map((item, i) => i === index ? { ...item, target_customer_hint: e.target.value } : item))} placeholder="Segmento, porte, equipe ou cargo" /></label><label>Diferenciais e restrições<textarea rows={2} value={offer.differentiators} onChange={(e) => setOffers(offers.map((item, i) => i === index ? { ...item, differentiators: e.target.value } : item))} placeholder="Por que escolhem sua oferta?" /></label></div></div>)}</section>
      <div className="form-actions">{notice && <span className="notice inline-notice">{notice}</span>}<button className="primary" disabled={busy}>{busy ? "Salvando…" : "Salvar perfil da oferta"}<span>→</span></button></div></form>
      {offers.some((offer) => offer.id) && <section className="card knowledge-card"><div className="card-heading"><span className="section-number">03</span><div><h3>Materiais da sua empresa</h3><p>Envie apresentações, cases, propostas ou materiais técnicos para embasar as recomendações.</p></div></div><div className="knowledge-toolbar"><label className="select-wrap">Oferta<select value={selectedOffer} onChange={(e) => setSelectedOffer(e.target.value)}>{offers.filter((offer) => offer.id).map((offer) => <option key={offer.id} value={offer.id}>{offer.name}</option>)}</select></label><label className={`upload-button ${busy ? "disabled-button" : ""}`}>＋ Adicionar documento<input type="file" accept=".pdf,.docx,.txt,.md" disabled={busy || !selectedOffer} onChange={upload} /></label></div><div className="file-list">{documents.length ? documents.map((doc) => <div className="file-row" key={doc.id}><span className="file-icon">↗</span><div><b>{doc.filename}</b><small>{doc.status === "failed" ? "Falha ao processar; tente enviar novamente" : doc.status === "indexed" ? "Texto extraído e pronto para consulta" : "Indexação em segundo plano"}</small></div><span className={`status ${doc.status}`}><i /> {doc.status === "indexed" ? "Indexado" : doc.status === "failed" ? "Falhou" : doc.status === "indexing" ? "Indexando" : "Na fila"}</span></div>) : <div className="empty-docs"><span>▧</span><p>Seus documentos aparecerão aqui.</p><small>PDF, DOCX, TXT e Markdown · até 20 MB por arquivo</small></div>}</div><div className="profile-action"><div><b>Perfil comercial e ICP sugerido</b><small>Use os dados e documentos para gerar uma primeira análise revisável.</small></div><button type="button" className="secondary" disabled={busy || !selectedOffer || documents.some((doc) => doc.status === "queued" || doc.status === "indexing")} onClick={generateProfile}>{busy ? "Analisando…" : "Gerar análise →"}</button></div></section>}
      {profile && <section className="card result-card"><div className="result-heading"><div><span className="eyebrow">{profileStatus === "approved" ? "ICP APROVADO" : "RASCUNHO PARA REVISÃO"}</span><h2>Perfil comercial sugerido</h2></div><span className="model-pill">{profile.generated_with}</span></div><p className="review-note">Revise os critérios sugeridos no formulário. Aprove o ICP quando os segmentos, portes e regiões estiverem corretos.</p><IcpEditor draft={profileDraft} onChange={setProfileDraft} /><details className="json-details"><summary>JSON completo</summary><label className="json-label">Perfil editável<textarea className="json-editor" spellCheck={false} value={profileDraft} onChange={(e) => setProfileDraft(e.target.value)} /></label></details><div className="profile-buttons"><button type="button" className="secondary" disabled={busy} onClick={() => saveProfile("draft")}>Salvar rascunho</button><button type="button" className="primary" disabled={busy} onClick={() => saveProfile("approved")}>Aprovar ICP <span>→</span></button></div><h3>Trechos utilizados</h3>{profile.evidence.length ? profile.evidence.map((item, i) => <blockquote key={i}><b>{item.filename}</b><p>{item.content}</p></blockquote>) : <p className="muted">Nenhum trecho de documento foi necessário para esta análise.</p>}</section>}
      <footer className="page-foot">LeadEngine360 <span>·</span> Seu conhecimento orienta a descoberta de oportunidades.</footer></div></section></main>;
}
