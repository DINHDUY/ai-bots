import { useQuery } from "@tanstack/react-query";
import { useParams } from "react-router-dom";
import { api, apiBase } from "../../api/client";
import { CaptureImage } from "../../components/ui/CaptureImage";
import "./center.css";

export function SharedView() {
  const { id } = useParams();
  const share = useQuery({
    queryKey: ["share", id],
    queryFn: () =>
      api<{
        expires_at: string;
        captures: { capture_id: string; url: string; expires_at?: string | null }[];
        artifacts: { id: string; url: string }[];
      }>(`/api/shares/${id}`),
    refetchInterval: 3000,
    retry: false,
  });
  if (share.isError)
    return (
      <section className="workspace-center">
        <h1>Share unavailable</h1>
        <p>
          This share may have expired or been revoked, or your account is not
          its recipient.
        </p>
      </section>
    );
  return (
    <section className="workspace-center">
      <h1>Shared view</h1>
      <p>View only · expires {share.data?.expires_at}</p>
      {share.data?.captures.map((c) => (
        <CaptureImage
          expiresAt={c.expires_at}
          onUnavailable={() => void share.refetch()}
          key={c.capture_id}
          style={{ maxWidth: "100%" }}
          src={apiBase() + c.url}
          crossOrigin="use-credentials"
          alt="Selected shared surface"
        />
      ))}
      {share.data?.artifacts.map((a) => (
        <p key={a.id}>
          <a href={apiBase() + a.url}>Download retained artifact {a.id}</a>
        </p>
      ))}
    </section>
  );
}
