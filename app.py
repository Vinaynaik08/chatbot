from flask import Flask, request, jsonify, render_template
import google.generativeai as genai

# ---------- Configure Gemini API ----------
# Replace this with your working Gemini API key
genai.configure(api_key="AIzaSyCMprjgZrkdhY-fHXLf-v_RrFHm1mtdJEo")

# Update to the correct model name for your account
model = genai.GenerativeModel("gemini-2.0-flash")

app = Flask(__name__)

# ---------- Database schema (unchanged) ----------
schema = """
generator client {
  provider = "prisma-client-js"
  output   = "orm"
  binaryTargets = ["native", "debian-openssl-3.0.x"]
}

datasource db {
 provider = "postgresql"
  url      = env("DATABASE_URL")
}

model District {
  district_id   Int      @id @default(autoincrement())
  district_name String   @db.VarChar(100)
  assets        Asset[]
  created_at    DateTime @default(now())
  updated_at    DateTime @updatedAt

  @@map("districts")
}

model Asset {
  asset_id       Int       @id @default(autoincrement())
  asset_code     String    @unique @db.VarChar(50)
  asset_name     String    @db.VarChar(100)
  district_id    Int
  district       District  @relation(fields: [district_id], references: [district_id])
  snapshots      Snapshot[]
  is_commercial    Boolean       @default(false)
  gst_number     String?   @db.VarChar(20)
  pan_number     String?   @db.VarChar(20)
  location       String?   @db.VarChar(200)
  other_info     Json?
  created_at     DateTime  @default(now())
  updated_at     DateTime  @updatedAt
  group_json_dumps DumpHistory[]

  @@map("assets")
  @@index([district_id])
}

model Snapshot {
  snapshot_id     Int              @id @default(autoincrement())
  asset_id        Int
  asset           Asset            @relation(fields: [asset_id], references: [asset_id])
  snapshot_date   DateTime
  groups          GroupSummary[]
  inventory_items InventorySummary[]
  overall_debit   Float            @default(0)
  overall_credit  Float            @default(0)
  overall_net     Float            @default(0)
  metadata        Json?
  created_at      DateTime         @default(now())

  @@unique([asset_id, snapshot_date])
  @@map("snapshots")
  @@index([asset_id])
  @@index([snapshot_date])
}

model GroupSummary {
  group_id         Int             @id @default(autoincrement())
  snapshot_id      Int
  snapshot         Snapshot        @relation(fields: [snapshot_id], references: [snapshot_id])
  group_name       String          @db.VarChar(200)
  group_type       String          @db.VarChar(50)
  group_debit      Float           @default(0)
  group_credit     Float           @default(0)
  net_amount       Float           @default(0)
  extra_data       Json?

  parent_group_id  Int?
  parent_group     GroupSummary?   @relation("GroupHierarchy", fields: [parent_group_id], references: [group_id])
  child_groups     GroupSummary[]  @relation("GroupHierarchy")

  ledgers          LedgerDetail[]

  @@unique([snapshot_id, group_name])
  @@map("group_summaries")
  @@index([snapshot_id])
  @@index([group_name, snapshot_id])
}

model LedgerDetail {
  ledger_id         Int             @id @default(autoincrement())
  group_id          Int
  group             GroupSummary    @relation(fields: [group_id], references: [group_id])

  parent_ledger_id  Int?
  parent_ledger     LedgerDetail?   @relation("LedgerHierarchy", fields: [parent_ledger_id], references: [ledger_id])
  child_ledgers     LedgerDetail[]  @relation("LedgerHierarchy")

  ledger_name       String          @db.VarChar(200)
  ledger_debit      Float           @default(0)
  ledger_credit     Float           @default(0)
  extra_data        Json?

  @@map("ledger_details")
  @@index([group_id])
}

model InventorySummary {
  inventory_id  Int       @id @default(autoincrement())
  snapshot_id   Int
  snapshot      Snapshot  @relation(fields: [snapshot_id], references: [snapshot_id])
  item_name     String    @db.VarChar(100)
  quantity      Int       @default(0)
  value         Float     @default(0)
  rate          Float     @default(0)
  extra_data    Json?

  @@map("inventory_summary")
}

model Users {
  user_id       Int      @id @default(autoincrement())
  username      String   @unique @db.VarChar(50)
  password_hash String   @db.VarChar(255)
  email         String   @unique @db.VarChar(100)
  role          String?  @db.VarChar(10)
  created_at    DateTime @default(now())
  updated_at    DateTime @updatedAt

  @@map("users")
}

model DumpHistory {
  dump_id    Int      @id @default(autoincrement())
  asset_id   Int
  asset      Asset    @relation(fields: [asset_id], references: [asset_id])
  dump_date  DateTime @default(now())
  created_at DateTime @default(now())

  @@map("asset_group_json_dumps")
  @@index([asset_id, dump_date])
}

model StoredQuery {
  query_id Int    @id @default(autoincrement())
  name     String @db.Text
  query    String @db.Text

  @@map("stored_queries")
}

model Session {
  id        String        @id @default(uuid())
  createdAt DateTime      @default(now())
  messages  ChatMessage[] @relation("SessionMessages")

  @@map("chat_sessions")
}

model ChatMessage {
  id        String   @id @default(uuid())
  sessionId String
  session   Session  @relation("SessionMessages", fields: [sessionId], references: [id])
  question  String   @db.Text
  answer    String   @db.Text
  query     String?  @db.Text
  createdAt DateTime @default(now())

  @@map("chat_messages")
}
"""

# ---------- Per-user state ----------
user_state = {}

@app.route("/")
def index():
    return render_template("index.html")

@app.route("/ask", methods=["POST"])
def ask():
    data = request.json
    user_id = data["user_id"]
    prompt = data["prompt"]

    if user_id not in user_state:
        user_state[user_id] = {"schema_sent": False, "tokens_schema": 0, "tokens_prompt": 0}

    if not user_state[user_id]["schema_sent"]:
        full_prompt = f"""
You are an expert SQL query generator.
Given the following database schema and user request, return only the SQL query.

Schema:
{schema}

User request:
{prompt}
"""
        user_state[user_id]["schema_sent"] = True
        first_time = True
    else:
        full_prompt = f"""
You are an expert SQL query generator.
Return only the SQL query (no explanation).

User request:
{prompt}
"""
        first_time = False

    # ---------- Generate response ----------
    response = model.generate_content(full_prompt)

    # ---------- Token tracking ----------
    tokens_used = response.usage_metadata.total_token_count
    if first_time:
        user_state[user_id]["tokens_schema"] += tokens_used
    else:
        user_state[user_id]["tokens_prompt"] += tokens_used

    return jsonify({
        "sql": response.text.strip(),
        "tokens_schema": user_state[user_id]["tokens_schema"],
        "tokens_prompt": user_state[user_id]["tokens_prompt"]
    })

if __name__ == "__main__":
    app.run(debug=True)
