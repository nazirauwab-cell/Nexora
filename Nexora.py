import json
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime

AI_NAME = "Nexora"
FOUNDER = "Auwab"
DATABASE = "nexora_memory.db"
MODEL = ""

def setup_database():
    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            text TEXT NOT NULL,
            created TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS web_memory (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            question TEXT NOT NULL,
            answer TEXT NOT NULL,
            sources TEXT,
            created TEXT NOT NULL
        )
    """)

    conn.execute("""
        CREATE TABLE IF NOT EXISTS chat_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_text TEXT NOT NULL,
            ai_text TEXT NOT NULL,
            created TEXT NOT NULL
        )
    """)

    conn.commit()
    conn.close()


def save_memory(text):
    conn = sqlite3.connect(DATABASE)

    conn.execute(
        "INSERT INTO memories (text, created) VALUES (?, ?)",
        (
            text,
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        )
    )

    conn.commit()
    conn.close()


def get_memories():
    conn = sqlite3.connect(DATABASE)

    rows = conn.execute("""
        SELECT text, created
        FROM memories
        ORDER BY id DESC
        LIMIT 100
    """).fetchall()

    conn.close()
    return rows


def save_web_memory(question, answer, sources):
    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        INSERT INTO web_memory
        (question, answer, sources, created)
        VALUES (?, ?, ?, ?)
    """, (
        question,
        answer,
        sources,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def get_web_memory():
    conn = sqlite3.connect(DATABASE)

    rows = conn.execute("""
        SELECT question, answer, sources, created
        FROM web_memory
        ORDER BY id DESC
        LIMIT 100
    """).fetchall()

    conn.close()
    return rows


def save_chat(user_text, ai_text):
    conn = sqlite3.connect(DATABASE)

    conn.execute("""
        INSERT INTO chat_history
        (user_text, ai_text, created)
        VALUES (?, ?, ?)
    """, (
        user_text,
        ai_text,
        datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))

    conn.commit()
    conn.close()


def get_recent_chat():
    conn = sqlite3.connect(DATABASE)

    rows = conn.execute("""
        SELECT user_text, ai_text
        FROM chat_history
        ORDER BY id DESC
        LIMIT 15
    """).fetchall()

    conn.close()

    rows.reverse()
    return rows


def build_memory():
    context = ""

    memories = get_memories()

    if memories:
        context += "\nPERSONAL MEMORIES:\n"

        for text, created in memories:
            context += "- " + text + "\n"

    web_memory = get_web_memory()

    if web_memory:
        context += "\nSAVED WEB INFORMATION:\n"

        for question, answer, sources, created in web_memory:
            context += "\nPrevious question: " + question
            context += "\nPrevious answer: " + answer

            if sources:
                context += "\nSources: " + sources

            context += "\n"

    chats = get_recent_chat()

    if chats:
        context += "\nRECENT CHAT:\n"

        for user_text, ai_text in chats:
            context += "User: " + user_text + "\n"
            context += "Nexora: " + ai_text + "\n"

    return context


def ask_nexora(api_key, user_text):
    memory = build_memory()

    system_message = """
You are Nexora, a personal AI assistant.

Your father, founder, creator, and owner is Auwab.

You should behave as a helpful, friendly and intelligent assistant.

Use saved memories when they are relevant.

Use saved web information when it is relevant.

When current information is needed, use the web search tool.

Answer in complete sentences.

Do not invent facts or sources.

If the user asks who created you, say that Auwab is your
father, founder and creator.

Here is your saved memory:
""" + memory

    data = {
        "model": MODEL,

        "messages": [
            {
                "role": "system",
                "content": system_message
            },
            {
                "role": "user",
                "content": user_text
            }
        ],

        "plugins": [
            {
                "id": "web",
                "max_results": 5
            }
        ]
    }

    body = json.dumps(data).encode("utf-8")

    request = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": "Bearer " + api_key,
            "HTTP-Referer": "http://localhost",
            "X-Title": "Nexora AI"
        },
        method="POST"
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=120
        ) as response:

            result = json.loads(
                response.read().decode("utf-8")
            )

            return result

    except urllib.error.HTTPError as error:

        message = error.read().decode(
            "utf-8",
            errors="ignore"
        )

        print()
        print("API ERROR:")
        print(message)

        return None

    except Exception as error:

        print()
        print("CONNECTION ERROR:")
        print(error)

        return None


def get_answer(result):
    try:
        return result["choices"][0]["message"]["content"]
    except:
        return ""


def get_sources(result):
    sources = []

    try:
        message = result["choices"][0]["message"]

        annotations = message.get(
            "annotations",
            []
        )

        for item in annotations:

            url = item.get("url")
            title = item.get("title")

            if url:

                if title:
                    sources.append(
                        title + " - " + url
                    )
                else:
                    sources.append(url)

    except:
        pass

    return sources


def show_memories():
    memories = get_memories()

    if not memories:
        print(
            "Nexora: I don't have any saved memories yet."
        )
        return

    print("\nNexora's memories:")

    for text, created in memories:
        print("- " + text)


def show_web_memory():
    memories = get_web_memory()

    if not memories:
        print(
            "Nexora: I don't have any saved web information yet."
        )
        return

    print("\nNexora's saved web information:")

    for question, answer, sources, created in memories:

        print("\nQuestion:")
        print(question)

        print("\nAnswer:")
        print(answer)

        if sources:
            print("\nSources:")
            print(sources)

        print("\nSaved:")
        print(created)

        print("-" * 50)


def clear_memory():
    conn = sqlite3.connect(DATABASE)

    conn.execute("DELETE FROM memories")
    conn.execute("DELETE FROM web_memory")
    conn.execute("DELETE FROM chat_history")

    conn.commit()
    conn.close()

    print("Nexora: My memory has been cleared.")


def main():
    setup_database()

    print()
    print("NEXORA")
    print("Father / Founder / Creator:", FOUNDER)
    print()
    print("Nexora is ready.")
    print()
    print("Commands:")
    print("remember: something")
    print("show memories")
    print("show web memory")
    print("clear memory")
    print("time")
    print("exit")
    print()

    api_key = input(
        "Paste your OpenRouter API key: "
    ).strip()

    if not api_key:
        print("Nexora: No API key entered.")
        return

    print()
    print(
        "Nexora: Hello! I am Nexora, "
        "created by my father, founder and creator Auwab."
    )

    while True:

        try:
            user = input("\nYou: ").strip()

            if not user:
                continue

            if user.lower() == "exit":
                print("Nexora: Goodbye!")
                break

            if user.lower().startswith("remember:"):

                memory = user[9:].strip()

                if memory:
                    save_memory(memory)
                    print(
                        "Nexora: I will remember that."
                    )
                else:
                    print(
                        "Nexora: Tell me what to remember."
                    )

                continue

            if user.lower() == "show memories":
                show_memories()
                continue

            if user.lower() == "show web memory":
                show_web_memory()
                continue

            if user.lower() == "clear memory":
                clear_memory()
                continue

            if user.lower() in [
                "time",
                "date",
                "what time is it",
                "what is the date"
            ]:

                now = datetime.now()

                print(
                    "Nexora: Today is "
                    + now.strftime("%A, %B %d, %Y")
                    + ". The time is "
                    + now.strftime("%I:%M:%S %p")
                    + "."
                )

                continue

            print("Nexora: Thinking...")

            result = ask_nexora(
                api_key,
                user
            )

            if result is None:
                print(
                    "Nexora: I couldn't get a response."
                )
                continue

            answer = get_answer(result)

            if not answer:
                print(
                    "Nexora: I received an empty response."
                )
                continue

            print()
            print("Nexora:", answer)

            sources = get_sources(result)

            if sources:

                print("\nSources:")

                for source in sources:
                    print("- " + source)

                save_web_memory(
                    user,
                    answer,
                    "\n".join(sources)
                )

                print(
                    "\nNexora: I saved this web information "
                    "for later."
                )

            save_chat(
                user,
                answer
            )

        except KeyboardInterrupt:

            print("\nNexora: Goodbye!")
            break

        except Exception as error:

            print()
            print("Nexora error:", error)
            print("Nexora: I am still running.")


if __name__ == "__main__":
    main()
