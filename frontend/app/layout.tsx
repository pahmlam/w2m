import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "W2M — Where to meet",
  description: "Tìm điểm gặp dựa trên thời gian di chuyển của cả nhóm.",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="vi">
      <body>{children}</body>
    </html>
  );
}
