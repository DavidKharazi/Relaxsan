import os
from typing import Optional, Dict, Any
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_core.documents import Document
from langchain_community.vectorstores import Chroma
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
import sqlite3
from langchain_core.runnables.history import RunnableWithMessageHistory
from langchain_community.chat_message_histories import ChatMessageHistory
from langchain_core.prompts.chat import ChatPromptTemplate, MessagesPlaceholder
from langchain.schema import AIMessage, HumanMessage, SystemMessage
from fastapi import FastAPI, HTTPException
import uvicorn
import boto3
from fnmatch import fnmatchcase
import json
from typing import List, Tuple


os.environ['OPENAI_API_KEY'] = 'my-api-key'


model_name = "gpt-3.5-turbo"
temperature = 0
llm = ChatOpenAI(model=model_name, temperature=temperature)

embeddings = OpenAIEmbeddings()

current_user = 'RELAXSAN'

# Настройка клиента для Yandex S3
session = boto3.session.Session()
s3_client = session.client(
    service_name='s3',
    endpoint_url='https://storage.yandexcloud.net',
    aws_access_key_id='my_access_key_id',
    aws_secret_access_key='my_secret_access_key',
)

CHROMA_PATH = f'./chroma/{current_user}/new/'


def init_metadata_db():
    with sqlite3.connect('metadata.db') as conn:
        conn.execute('''
        CREATE TABLE IF NOT EXISTS uploaded_docs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        global_source TEXT,
        filename TEXT
        );
        ''')
        conn.execute('''
        CREATE TABLE IF NOT EXISTS history_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id TEXT,
                user_type TEXT,
                message TEXT,
                tmstmp DATETIME DEFAULT CURRENT_TIMESTAMP
        );
        ''')


init_metadata_db()


class SQLiteChatHistory():
    def __init__(self, db_path="metadata.db"):
        self.db_path = db_path

    def add_message(self, message):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        if isinstance(message, HumanMessage):
            user_type = "human"
            message = message.content
        elif isinstance(message, AIMessage):
            user_type = "ai"
            message = message.content
        elif isinstance(message, SystemMessage):
            user_type = "system"
            message = message.content
        else:
            raise ValueError("Invalid message type")
        c.execute("INSERT INTO history_messages (user_id, user_type, message) VALUES (?, ?, ?)",
                  (current_user, user_type, message))
        conn.commit()
        conn.close()

    def messages(self, limit=15):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(f"SELECT * FROM history_messages WHERE user_id = '{current_user}' ORDER BY id DESC LIMIT {limit}")
        resp = c.fetchall()[::-1]
        chat_history = []
        for row in resp:
            id, user_id, user_type, message, tmstmp = row
            if user_type == "human":
                chat_history.append(HumanMessage(content=message))
            elif user_type == "ai":
                chat_history.append(AIMessage(content=message))
            elif user_type == "system":
                chat_history.append(SystemMessage(content=message))
        conn.commit()
        conn.close()
        messages = ChatMessageHistory(messages=chat_history)
        return messages

    def delete_chat_history_last_n(self, n=10):
        conn = sqlite3.connect(self.db_path)
        c = conn.cursor()
        c.execute(f'''
        with max_id as (select max(id) as maxid from history_messages where user_id = '{current_user}')
        DELETE FROM history_messages
        WHERE id BETWEEN (select maxid from max_id) - {n} AND (select maxid from max_id)
        ''')
        conn.commit()
        conn.close()


def add_filename_to_metadata(source, filename):
    with sqlite3.connect('metadata.db') as conn:
        conn.execute(f'''INSERT INTO uploaded_docs (global_source, filename) values ('{source}', '{filename}') ; ''')


def delete_filename_from_metadata(source, filename):
    with sqlite3.connect('metadata.db') as conn:
        conn.execute(f'''DELETE from uploaded_docs where global_source = '{source}' and filename ='{filename}' ; ''')



class Document:
    def __init__(self, source: str, page_content: str, metadata: Optional[Dict[str, Any]] = None):
        self.source = source
        self.page_content = page_content
        self.metadata = metadata if metadata is not None else {'source': source}



def get_uploaded_filenames(source) -> List[str]:
    with sqlite3.connect('metadata.db') as conn:
        cursor = conn.cursor()
        cursor.execute(f"SELECT filename FROM uploaded_docs WHERE global_source = ?", (source,))
        rows = cursor.fetchall()
    filenames = [row[0] for row in rows]
    return filenames


def load_s3_files(bucket: str, prefix: str, suffix: str) -> List[str]:
    try:
        response = s3_client.list_objects_v2(Bucket=bucket, Prefix=prefix)
        contents = response.get('Contents', [])
        if not contents:
            return []
        files = [content['Key'] for content in contents if content['Key'].endswith(suffix)]
        return files
    except Exception as e:
        print(f"Error loading S3 files: {e}")
        return []


def load_docx_new(source, bucket: str) -> List[Document]:
    prefix = 'RELAXSAN/docx/'
    suffix = '.docx'
    files = load_s3_files(bucket, prefix, suffix)
    uniq_files = get_uploaded_filenames(source) or []

    docs = []
    for file in files:
        if not any(fnmatchcase(file, f"*{pattern}*") for pattern in uniq_files):
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=file)
                content = obj['Body'].read().decode('utf-8')
                docs.append(Document(source=file, page_content=content))
            except Exception as e:
                print(f"Error reading txt file {file}: {e}")

    return docs if docs else None


def load_txts(source, bucket: str) -> List[Document]:
    prefix = 'RELAXSAN/txt/'
    suffix = '.txt'
    files = load_s3_files(bucket, prefix, suffix)
    uniq_files = get_uploaded_filenames(source) or []

    docs = []
    for file in files:
        if not any(fnmatchcase(file, f"*{pattern}*") for pattern in uniq_files):
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=file)
                content = obj['Body'].read().decode('utf-8')
                docs.append(Document(source=file, page_content=content))
            except Exception as e:
                print(f"Error reading txt file {file}: {e}")

    return docs if docs else None


def load_jsons(source, bucket: str) -> Tuple[List[Document], List[dict]]:
    prefix = 'RELAXSAN/json/'
    suffix = '.json'
    files = load_s3_files(bucket, prefix, suffix)
    uniq_files = get_uploaded_filenames(source) or []

    json_docs, json_metadata = [], []
    for file in files:
        if not any(fnmatchcase(file, f"*{pattern}*") for pattern in uniq_files):
            try:
                obj = s3_client.get_object(Bucket=bucket, Key=file)
                content = json.loads(obj['Body'].read().decode('utf-8'))
                json_docs.append(content)
                json_metadata.append({'source': file})
            except Exception as e:
                print(f"Error reading json file {file}: {e}")

    return (json_docs, json_metadata) if json_docs else (None, None)


def load_documents(global_source, bucket: str, file_types: List[str]) -> dict:
    """
    Загружаем документы в зависимости от типа документа из Yandex S3
    """
    all_docs = {'txt': None, 'json': None, 'json_metadata': None, 'docx': None}
    if 'txt' in file_types:
        txt_docs = load_txts(global_source, bucket)
        all_docs['txt'] = txt_docs
    if 'json' in file_types:
        json_docs, json_metadata = load_jsons(global_source, bucket)
        all_docs['json'] = json_docs
        all_docs['json_metadata'] = json_metadata
    if 'docx' in file_types:
        docx_docs = load_docx_new(global_source, bucket)
        all_docs['docx'] = docx_docs
    return all_docs


# Пример использования
DATA_BUCKET = 'utlik'
DOCS = load_documents('local', DATA_BUCKET, ['txt', 'json', 'docx'])


import re

def split_docs_to_chunks(documents: dict, file_types: List[str], keyword="Идентификатор"):
    all_chunks = []

    def split_by_keyword(text, keyword):
        # Разделяем текст по ключевому слову и сохраняем ключевое слово в начале каждого чанка
        parts = re.split(f"({keyword})", text)
        chunks = [parts[i] + parts[i + 1] for i in range(1, len(parts) - 1, 2)]
        if parts[0]:
            chunks.insert(0, parts[0])
        if len(parts) % 2 == 0:
            chunks.append(parts[-1])
        return chunks

    if 'txt' in file_types and documents['txt'] is not None:
        for doc in documents['txt']:
            chunks = split_by_keyword(doc.page_content, keyword)
            for chunk in chunks:
                all_chunks.append(Document(source=doc.source, page_content=chunk, metadata=doc.metadata))

    if 'json' in file_types and documents['json'] is not None:
        for idx, doc in enumerate(documents['json']):
            text = json.dumps(doc, ensure_ascii=False)
            chunks = split_by_keyword(text, keyword)
            for chunk in chunks:
                all_chunks.append(Document(source=documents['json_metadata'][idx]['source'], page_content=chunk))

    if 'docx' in file_types and documents['docx'] is not None:
        for doc in documents['docx']:
            chunks = split_by_keyword(doc.page_content, keyword)
            for chunk in chunks:
                all_chunks.append(Document(source=doc.source, page_content=chunk, metadata=doc.metadata))

    return all_chunks


chunks_res = split_docs_to_chunks(DOCS, ['txt', 'json', 'docx'])


def get_chroma_vectorstore(documents, embeddings, persist_directory):
    if os.path.isdir(persist_directory) and os.listdir(persist_directory):
        print("Loading existing Chroma vectorstore...")
        vectorstore = Chroma(
            embedding_function=embeddings, persist_directory=persist_directory
        )

        existing_files = get_uploaded_filenames('local')
        uniq_sources_to_add = set(
            doc.metadata['source'] for doc in chunks_res
            if doc.metadata['source'] not in existing_files
        )

        if uniq_sources_to_add:
            vectorstore.add_documents(
                documents=[doc for doc in chunks_res if doc.metadata['source'] in uniq_sources_to_add],
                embedding=embeddings
            )
            for filename in uniq_sources_to_add:
                add_filename_to_metadata('local', filename)
        else:
            print('Новых документов не было, пропускаем шаг добавления')

    else:
        print("Creating and indexing new Chroma vectorstore...")
        vectorstore = Chroma.from_documents(
            documents=documents,
            embedding=embeddings, persist_directory=persist_directory
        )
        uniq_sources_to_add = set(doc.metadata['source'] for doc in documents)
        for filename in uniq_sources_to_add:
            add_filename_to_metadata('local', filename)

    return vectorstore


vectorstore = get_chroma_vectorstore(documents=chunks_res, embeddings=embeddings, persist_directory=CHROMA_PATH)
retriever = vectorstore.as_retriever(search_kwargs={"k": 2}, search_type='similarity')


def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)


chat_history_for_chain = SQLiteChatHistory()


prompt_new = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            '''You are an assistant for question-answering tasks. Use the following pieces of retrieved context to answer the question.
            You can also use information from chat_history if necessary.
            If you don't know the answer, just say that you don't know. Use three sentences maximum and keep the answer concise.
            The context which you should use: {context}
            Provide information on product availability
            Answer essentially what is being asked, without unnecessary information
            ''',
        ),
        MessagesPlaceholder(variable_name="chat_history"),
        ("human", "{question}"),
    ]
)

chain_new = prompt_new | llm

chain_with_message_history = RunnableWithMessageHistory(
    chain_new,
    lambda session_id: chat_history_for_chain.messages(limit=10),
    input_messages_key="question",
    history_messages_key="chat_history",
)

app = FastAPI()


@app.post("/rag_chat/")
async def ask_question(question_data: dict = None):
    if question_data is None:
        raise HTTPException(status_code=400, detail="Question data is required")

    question = question_data.get('question', None)
    if question is None:
        raise HTTPException(status_code=400, detail="Question is required")

    answer = chain_with_message_history.invoke({"question": question, "context": format_docs(retriever.invoke(question))},
                                               {"configurable": {"session_id": 1}})
    answer = answer.content
    if answer is not None:
        chat_history_for_chain.add_message(HumanMessage(content=question))
        chat_history_for_chain.add_message(AIMessage(content=answer))

    return {"answer": answer}


if __name__ == "__main__":
    uvicorn.run("app:app", host="0.0.0.0", port=8123, reload=True)
