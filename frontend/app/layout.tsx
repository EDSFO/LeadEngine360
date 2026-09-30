import type { Metadata } from "next";
import "./styles.css";

export const metadata: Metadata = {
  title: "LeadEngine360 | Inteligência comercial",
  description: "Transforme o conhecimento sobre sua oferta em oportunidades B2B mais relevantes.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="pt-BR"><body>{children}</body></html>;
}
