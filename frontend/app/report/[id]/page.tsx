import { ReportScreen } from "@/components/report/ReportView";

export default async function ReportPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  return <ReportScreen id={decodeURIComponent(id)} />;
}
