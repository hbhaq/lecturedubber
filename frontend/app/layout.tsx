import "./globals.css";
import AuthGate from "../components/AuthGate";
export const metadata = {
  title: "Lecture Studio",
  description: "Teach once. Share in English.",
};
export default function Layout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <AuthGate>{children}</AuthGate>
      </body>
    </html>
  );
}
