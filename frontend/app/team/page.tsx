"use client";

import { FormEvent, useEffect, useState } from "react";
import "../styles.css";
import "./team.css";

type Member = { id: string; email: string; role: string };
const roles = [
  ["manager", "Gestor comercial"],
  ["analyst", "Analista"],
  ["sdr", "SDR/BDR"],
  ["closer", "Closer"],
  ["admin", "Administrador"],
];

async function api(path: string, token: string, init?: RequestInit) {
  const response = await fetch(`/api/v1${path}`, { ...init, headers: { ...(init?.headers || {}), Authorization: `Bearer ${token}` } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || "Não foi possível concluir a solicitação.");
  return body;
}

export default function TeamPage() {
  const [token, setToken] = useState("");
  const [role, setRole] = useState("");
  const [members, setMembers] = useState<Member[]>([]);
  const [email, setEmail] = useState("");
  const [inviteRole, setInviteRole] = useState("sdr");
  const [inviteLink, setInviteLink] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  useEffect(() => { setToken(window.localStorage.getItem("le360_token") || ""); }, []);
  useEffect(() => {
    if (!token) return;
    api("/me", token).then((me) => {
      setRole(me.role || "");
      if (me.role === "admin") return api("/users", token).then(setMembers);
    }).catch((error) => setNotice(error.message));
  }, [token]);

  async function invite(event: FormEvent) {
    event.preventDefault(); setBusy(true); setNotice("");
    try {
      const result = await api("/users/invitations", token, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ email, role: inviteRole }) });
      setInviteLink(`${window.location.origin}/join?token=${encodeURIComponent(result.token)}`);
      setNotice("Convite criado. Copie o link e envie-o à pessoa convidada por um canal de sua escolha.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível criar o convite."); }
    finally { setBusy(false); }
  }

  async function changeRole(member: Member, nextRole: string) {
    setBusy(true); setNotice("");
    try {
      const updated = await api(`/users/${member.id}/role`, token, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ role: nextRole }) });
      setMembers((current) => current.map((item) => item.id === member.id ? updated : item));
      setNotice("Papel atualizado.");
    } catch (error) { setNotice(error instanceof Error ? error.message : "Não foi possível alterar o papel."); }
    finally { setBusy(false); }
  }

  return <main className="team-page"><header><a href="/">← Voltar ao LeadEngine360</a><h1>Equipe</h1><p>Convide pessoas para o tenant e defina o papel de cada uma.</p></header>
    {notice && <div className="notice">{notice}</div>}
    {!token ? <p>Entre na sua conta para continuar.</p> : role !== "admin" ? <p>Somente administradores podem gerenciar a equipe.</p> : <>
      <section className="card"><h2>Novo convite</h2><form onSubmit={invite}><label>E-mail<input type="email" required value={email} onChange={(event) => setEmail(event.target.value)} /></label><label>Papel<select value={inviteRole} onChange={(event) => setInviteRole(event.target.value)}>{roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><button className="primary" disabled={busy}>Criar convite</button></form>{inviteLink && <div className="invite-link"><label>Link válido por 7 dias<input readOnly value={inviteLink} onFocus={(event) => event.target.select()} /></label><button className="secondary" onClick={() => void navigator.clipboard.writeText(inviteLink)}>Copiar link</button></div>}</section>
      <section className="card"><h2>Pessoas ativas</h2><div className="member-list">{members.map((member) => <div className="member-row" key={member.id}><span>{member.email}</span><select aria-label={`Papel de ${member.email}`} value={member.role} disabled={busy} onChange={(event) => void changeRole(member, event.target.value)}>{roles.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></div>)}</div></section>
    </>}
  </main>;
}
