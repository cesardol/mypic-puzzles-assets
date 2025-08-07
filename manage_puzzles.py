import streamlit as st
import os
import pandas as pd
import datetime
import json

# --- Config ---
BASE_URL = "https://mypicpuzzles.netlify.app"

def scan_images(root_folder):
    records = []
    for dirpath, dirnames, filenames in os.walk(root_folder):
        # Category is last part of dirpath (skip root itself)
        category = os.path.basename(dirpath)
        for fname in filenames:
            if fname.lower().endswith(('.png', '.jpg', '.jpeg')):
                id = os.path.splitext(fname)[0]
                image_url = f"{BASE_URL}/{category}/{fname}"
                title = id
                # Default date: try to use yyyymmdd from id, else today
                try:
                    date = datetime.datetime.strptime(id[:8], "%Y%m%d").date()
                except:
                    date = datetime.date.today()
                records.append({
                    "id": id,
                    "title": title,
                    "image_url": image_url,
                    "category": category,
                    "date_available": date,
                })
    return pd.DataFrame(records)

def main():
    st.title("Puzzle JSON Manager")

    st.write("1. Select the root folder containing your category subfolders with images.")
    root = st.text_input("Root image folder (absolute path):", value=os.getcwd())
    if not os.path.isdir(root):
        st.error("Folder does not exist. Please enter a valid path.")
        return

    if st.button("Scan Images"):
        df = scan_images(root)
        st.session_state['df'] = df

    # Display table if we have scanned
    if 'df' in st.session_state:
        st.write("2. Edit the table below as needed. (Double-click to edit cells)")
        edited = st.data_editor(
            st.session_state['df'],
            num_rows="dynamic",
            use_container_width=True,
            column_config={
                "date_available": st.column_config.DateColumn(format="YYYY-MM-DD"),
            },
            key="edit_table"
        )

        st.write("3. Click below to export puzzles.json for the app.")
        json_data = edited.to_dict(orient="records")
        # Convert date_available to string for all rows
        for row in json_data:
            val = row["date_available"]
            if isinstance(val, (datetime.date, datetime.datetime)):
                row["date_available"] = val.isoformat()
            elif val is None:
                row["date_available"] = ""
            else:
                row["date_available"] = str(val)
        json_str = json.dumps(json_data, indent=2)
        st.download_button(
            label="Download puzzles.json",
            data=json_str,
            file_name="puzzles.json",
            mime="application/json"
        )

if __name__ == "__main__":
    main()
