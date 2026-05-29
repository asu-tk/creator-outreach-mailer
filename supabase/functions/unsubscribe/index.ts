const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";

function text(message: string, detail = "") {
  const body = `${message}\n\n${
    detail ||
    "今後、こちらのメールアドレス宛へのご案内は停止いたします。お手数をおかけし、申し訳ございませんでした。"
  }`;
  return new Response(body, {
    status: 200,
    headers: {
      "Content-Type": "text/plain; charset=utf-8",
      "Cache-Control": "no-store",
    },
  });
}

async function supabaseRequest(path: string, options: RequestInit = {}) {
  const response = await fetch(`${SUPABASE_URL}/rest/v1/${path}`, {
    ...options,
    headers: {
      apikey: SERVICE_ROLE_KEY,
      Authorization: `Bearer ${SERVICE_ROLE_KEY}`,
      "Content-Type": "application/json",
      ...(options.headers ?? {}),
    },
  });
  if (!response.ok) {
    const detail = await response.text();
    throw new Error(`Supabase ${response.status}: ${detail}`);
  }
  const responseText = await response.text();
  return responseText ? JSON.parse(responseText) : [];
}

function encodeFilter(value: unknown) {
  return encodeURIComponent(String(value ?? "").trim());
}

async function refreshSendJob(jobId: string) {
  if (!jobId) return;
  const encodedJobId = encodeFilter(jobId);
  const rows = await supabaseRequest(`send_queue?job_id=eq.${encodedJobId}&select=status`);
  const sent = rows.filter((row: { status: string }) => row.status === "sent").length;
  const failed = rows.filter((row: { status: string }) => row.status === "failed").length;
  const pending = rows.filter((row: { status: string }) => row.status === "pending" || row.status === "sending").length;
  const status = pending === 0 ? "finished" : "sending";
  const now = new Date().toISOString();

  await supabaseRequest(`send_jobs?id=eq.${encodedJobId}`, {
    method: "PATCH",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({
      total_count: rows.length,
      sent_count: sent,
      failed_count: failed,
      status,
      updated_at: now,
      ...(status === "finished" ? { finished_at: now } : { started_at: now }),
    }),
  });
}

async function blockTarget(item: Record<string, unknown>, now: string) {
  const userEmail = String(item.user_email ?? "").trim().toLowerCase();
  const contactEmail = String(item.contact_email ?? "").trim().toLowerCase();
  const channelId = String(item.youtube_channel_id ?? "").trim();
  const channel = String(item.channel ?? "").trim();
  if (!userEmail || (!contactEmail && !channelId)) return;

  const encodedUserEmail = encodeFilter(userEmail);
  if (contactEmail) {
    const existing = await supabaseRequest(
      `blocked_targets?user_email=eq.${encodedUserEmail}&email=eq.${encodeFilter(contactEmail)}&select=id&limit=1`,
    );
    if (existing.length) return;
  }
  if (channelId) {
    const existing = await supabaseRequest(
      `blocked_targets?user_email=eq.${encodedUserEmail}&youtube_channel_id=eq.${encodeFilter(channelId)}&select=id&limit=1`,
    );
    if (existing.length) return;
  }

  await supabaseRequest("blocked_targets", {
    method: "POST",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({
      user_email: userEmail,
      email: contactEmail,
      youtube_channel_id: channelId,
      channel,
      reason: "配信停止URL",
      created_at: now,
    }),
  });
}

async function deletePendingQueue(item: Record<string, unknown>) {
  const userEmail = String(item.user_email ?? "").trim().toLowerCase();
  const contactEmail = String(item.contact_email ?? "").trim().toLowerCase();
  const contactLocalId = Number(item.contact_local_id ?? 0);
  if (!userEmail || (!contactEmail && !contactLocalId)) return 0;

  const encodedUserEmail = encodeFilter(userEmail);
  const filters: string[] = [];
  if (contactEmail) filters.push(`contact_email=eq.${encodeFilter(contactEmail)}`);
  if (contactLocalId) filters.push(`contact_local_id=eq.${contactLocalId}`);

  const affectedJobIds = new Set<string>();
  let deletedCount = 0;
  for (const filter of filters) {
    const deletedRows = await supabaseRequest(
      `send_queue?user_email=eq.${encodedUserEmail}&status=eq.pending&${filter}&select=id,job_id`,
      {
        method: "DELETE",
        headers: { Prefer: "return=representation" },
      },
    );
    deletedCount += deletedRows.length;
    for (const row of deletedRows) {
      if (row.job_id) affectedJobIds.add(String(row.job_id));
    }
  }

  for (const jobId of affectedJobIds) {
    await refreshSendJob(jobId);
  }
  return deletedCount;
}

Deno.serve(async (req: Request) => {
  try {
    if (!SUPABASE_URL || !SERVICE_ROLE_KEY) {
      return text("配信停止を受け付けられませんでした", "恐れ入りますが、送信者へ直接ご連絡ください。");
    }

    const url = new URL(req.url);
    const token = (url.searchParams.get("token") ?? "").trim();
    if (!token) {
      return text("配信停止URLが正しくありません", "恐れ入りますが、URLが途中で切れていないかご確認ください。");
    }

    const encodedToken = encodeURIComponent(token);
    const rows = await supabaseRequest(`unsubscribe_tokens?token=eq.${encodedToken}&select=*`);
    if (!rows.length) {
      return text("配信停止URLを確認できませんでした", "すでに配信停止済み、またはURLが正しくない可能性があります。お手数をおかけし申し訳ございません。");
    }

    const item = rows[0];
    const now = new Date().toISOString();
    await supabaseRequest(`unsubscribe_tokens?token=eq.${encodedToken}`, {
      method: "PATCH",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({ unsubscribed_at: item.unsubscribed_at || now, updated_at: now }),
    });

    await blockTarget(item, now);
    await deletePendingQueue(item);

    return text(
      "配信停止を受け付けました",
      "このたびはご案内メールによりお手数をおかけし、申し訳ございません。\n今後、こちらのメールアドレス宛へのご案内は停止いたします。\n未送信の予約がある場合も送信対象から外しました。\nご対応いただき、ありがとうございました。",
    );
  } catch (_error) {
    return text("配信停止を受け付けられませんでした", "恐れ入りますが、時間をおいて再度お試しください。解決しない場合は、送信者へ直接ご連絡ください。");
  }
});
