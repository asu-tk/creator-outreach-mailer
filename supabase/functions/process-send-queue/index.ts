import nodemailer from "npm:nodemailer@6.9.16";

const SUPABASE_URL = Deno.env.get("SUPABASE_URL") ?? "";
const SERVICE_ROLE_KEY = Deno.env.get("SUPABASE_SERVICE_ROLE_KEY") ?? "";
const WORKER_SECRET = Deno.env.get("WORKER_SECRET") ?? "";
const NOTIFY_SMTP_HOST = Deno.env.get("NOTIFY_SMTP_HOST") ?? "";
const NOTIFY_SMTP_PORT = Deno.env.get("NOTIFY_SMTP_PORT") ?? "587";
const NOTIFY_SMTP_SSL = (Deno.env.get("NOTIFY_SMTP_SSL") ?? "false").toLowerCase() === "true";
const NOTIFY_SMTP_USER = Deno.env.get("NOTIFY_SMTP_USER") ?? "";
const NOTIFY_SMTP_PASS = Deno.env.get("NOTIFY_SMTP_PASS") ?? "";
const NOTIFY_MAIL_FROM = Deno.env.get("NOTIFY_MAIL_FROM") ?? NOTIFY_SMTP_USER;

function jsonResponse(data: unknown, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
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
  const text = await response.text();
  return text ? JSON.parse(text) : [];
}

function encodeFilter(value: unknown) {
  return encodeURIComponent(String(value ?? "").trim());
}

function mailFrom(job: Record<string, unknown>) {
  const senderName = String(job.sender_name ?? "").trim();
  const senderEmail = String(job.sender_email ?? "").trim();
  return senderName ? `${senderName} <${senderEmail}>` : senderEmail;
}

function createTransporter(job: Record<string, unknown>) {
  const secure = Boolean(job.smtp_ssl);
  return nodemailer.createTransport({
    host: String(job.smtp_host),
    port: Number(job.smtp_port || 587),
    secure,
    requireTLS: !secure,
    auth: {
      user: String(job.sender_email),
      pass: String(job.smtp_pass),
    },
  });
}

function createNotifyTransporter(job: Record<string, unknown>) {
  if (NOTIFY_SMTP_HOST && NOTIFY_SMTP_USER && NOTIFY_SMTP_PASS) {
    return {
      transporter: nodemailer.createTransport({
        host: NOTIFY_SMTP_HOST,
        port: Number(NOTIFY_SMTP_PORT || 587),
        secure: NOTIFY_SMTP_SSL,
        requireTLS: !NOTIFY_SMTP_SSL,
        auth: {
          user: NOTIFY_SMTP_USER,
          pass: NOTIFY_SMTP_PASS,
        },
      }),
      from: NOTIFY_MAIL_FROM,
    };
  }
  return { transporter: createTransporter(job), from: mailFrom(job) };
}

async function markQueue(id: string, status: string, error = "") {
  await supabaseRequest(`send_queue?id=eq.${id}`, {
    method: "PATCH",
    headers: { Prefer: "return=minimal" },
    body: JSON.stringify({
      status,
      error,
      updated_at: new Date().toISOString(),
      ...(status === "sent" ? { sent_at: new Date().toISOString() } : {}),
    }),
  });
}

async function deleteQueue(id: string) {
  await supabaseRequest(`send_queue?id=eq.${id}`, {
    method: "DELETE",
    headers: { Prefer: "return=minimal" },
  });
}

async function hasUnsubscribeToken(item: Record<string, unknown>) {
  const userEmail = String(item.user_email ?? "").trim().toLowerCase();
  const contactEmail = String(item.contact_email ?? "").trim().toLowerCase();
  const contactLocalId = Number(item.contact_local_id ?? 0);
  if (!userEmail || (!contactEmail && !contactLocalId)) return false;

  const encodedUserEmail = encodeFilter(userEmail);
  const filters: string[] = [];
  if (contactEmail) filters.push(`contact_email=eq.${encodeFilter(contactEmail)}`);
  if (contactLocalId) filters.push(`contact_local_id=eq.${contactLocalId}`);

  for (const filter of filters) {
    const rows = await supabaseRequest(
      `unsubscribe_tokens?user_email=eq.${encodedUserEmail}&${filter}&unsubscribed_at=not.is.null&select=id&limit=1`,
    );
    if (Array.isArray(rows) && rows.length > 0) return true;
  }
  return false;
}

async function isBlockedTarget(item: Record<string, unknown>) {
  const userEmail = String(item.user_email ?? "").trim().toLowerCase();
  const contactEmail = String(item.contact_email ?? "").trim().toLowerCase();
  if (!userEmail || !contactEmail) return false;
  const rows = await supabaseRequest(
    `blocked_targets?user_email=eq.${encodeFilter(userEmail)}&email=eq.${encodeFilter(contactEmail)}&select=id&limit=1`,
  );
  return Array.isArray(rows) && rows.length > 0;
}

async function isUnsubscribed(item: Record<string, unknown>) {
  return (await hasUnsubscribeToken(item)) || (await isBlockedTarget(item));
}

async function sendCompletionNotice(job: Record<string, unknown>, sent: number, failed: number) {
  if (job.notified_at) return;
  const to = String(job.user_email ?? "").trim();
  if (!to) return;

  const { transporter, from } = createNotifyTransporter(job);
  const campaignName = String(job.campaign_name ?? "送信予約");
  const total = Number(job.total_count ?? 0);
  const subject = `送信作業が完了しました: ${campaignName}`;
  const body = `送信作業が完了しました。\n\n配信名: ${campaignName}\n予約数: ${total}件\n送信成功: ${sent}件\n送信失敗: ${failed}件\n\nCreator Outreach Mailer`;

  try {
    await transporter.sendMail({ from, to, subject, text: body });
    await supabaseRequest(`send_jobs?id=eq.${job.id}`, {
      method: "PATCH",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({ notified_at: new Date().toISOString(), notification_error: "" }),
    });
  } catch (error) {
    await supabaseRequest(`send_jobs?id=eq.${job.id}`, {
      method: "PATCH",
      headers: { Prefer: "return=minimal" },
      body: JSON.stringify({ notification_error: error instanceof Error ? error.message : String(error) }),
    });
  }
}

async function updateJob(jobId: string) {
  const rows = await supabaseRequest(`send_queue?job_id=eq.${jobId}&select=status`);
  const sent = rows.filter((row: { status: string }) => row.status === "sent").length;
  const failed = rows.filter((row: { status: string }) => row.status === "failed").length;
  const pending = rows.filter((row: { status: string }) => row.status === "pending" || row.status === "sending").length;
  const status = pending === 0 ? "finished" : "sending";
  const now = new Date().toISOString();

  await supabaseRequest(`send_jobs?id=eq.${jobId}`, {
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

  if (status === "finished") {
    const jobs = await supabaseRequest(`send_jobs?id=eq.${jobId}&select=*`);
    if (jobs.length) await sendCompletionNotice(jobs[0], sent, failed);
  }
}

Deno.serve(async (req: Request) => {
  if (WORKER_SECRET && req.headers.get("x-worker-secret") !== WORKER_SECRET) {
    return jsonResponse({ ok: false, error: "unauthorized" }, 401);
  }
  try {
    if (!SUPABASE_URL || !SERVICE_ROLE_KEY) {
      return jsonResponse({ ok: false, error: "Supabase environment variables are missing" }, 500);
    }

    const now = new Date().toISOString();
    const dueRows = await supabaseRequest(`send_queue?status=eq.pending&scheduled_at=lte.${encodeURIComponent(now)}&select=*&order=scheduled_at.asc&limit=1`);
    if (!dueRows.length) return jsonResponse({ ok: true, message: "no due emails" });

    const item = dueRows[0];
    await markQueue(item.id, "sending");

    const jobs = await supabaseRequest(`send_jobs?id=eq.${item.job_id}&select=*`);
    if (!jobs.length) {
      await markQueue(item.id, "failed", "send job not found");
      return jsonResponse({ ok: false, error: "send job not found" }, 404);
    }
    const job = jobs[0];

    try {
      if (await isUnsubscribed(item)) {
        await deleteQueue(item.id);
      } else {
        const transporter = createTransporter(job);
        await transporter.sendMail({
          from: mailFrom(job),
          to: String(item.contact_email),
          subject: String(item.subject),
          text: String(item.body),
        });
        await markQueue(item.id, "sent");
      }
    } catch (error) {
      await markQueue(item.id, "failed", error instanceof Error ? error.message : String(error));
    }

    await updateJob(String(item.job_id));
    return jsonResponse({ ok: true, processed: item.contact_email });
  } catch (error) {
    return jsonResponse({ ok: false, error: error instanceof Error ? error.message : String(error) }, 500);
  }
});
