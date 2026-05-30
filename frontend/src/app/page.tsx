import { redirect } from "next/navigation";

// Root → dashboard; the dashboard layout handles the auth check.
export default function RootPage() {
  redirect("/dashboard");
}
