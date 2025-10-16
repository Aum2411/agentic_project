import streamlit as st
import sqlite3
import os
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), '..', 'healthscope.db')

def get_reports():
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT id, patient_name, created_at, summary, symptoms, ai_outputs FROM reports ORDER BY created_at DESC")
    rows = cur.fetchall()
    conn.close()
    return rows

def download_report(report_id):
    # Placeholder: implement PDF export logic
    st.info(f"Download for report {report_id} coming soon.")

st.set_page_config(page_title="Patient Dashboard", layout="wide")
st.title("Patient Dashboard")

st.markdown("View your past uploaded reports, AI outputs, and symptom trends.")

reports = get_reports()

if not reports:
    st.warning("No reports found.")
else:
    for r in reports:
        rid, pname, created, summary, symptoms, ai_outputs = r
        with st.expander(f"Report for {pname or 'Unknown'} ({created})"):
            st.write("**Summary:**", summary)
            st.write("**Symptoms:**", symptoms)
            st.write("**AI Outputs:**", ai_outputs)
            st.button("Download PDF", on_click=lambda rid=rid: download_report(rid))

# Placeholder for trends/analytics
st.header("Symptom Trends Over Time")
st.line_chart([1,2,3,2,4,5])  # Replace with real data

# TODO: Implement PDF export and real analytics
