import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
# to view the visualiser run streamlit run visualiser.py

st.title('Prosperity 4 Data Visualiser')
st.text('Forgetful Functors')
st.markdown('This is a web app to explore prosperity 4 data from IMC')

uploaded_file = st.file_uploader('Upload trade history here')

if uploaded_file:
    df = pd.read_csv(uploaded_file, sep=';')

    st.header('Data Statstics')
    st.write(df.describe())

    st.header('Data Header')
    st.write(df.head())

    fig, ax = plt.subplots(1,1)

    ax.scatter(x=df['timestamp'], y=df['bid_price_1'])
    ax.set_xlabel('timestamp')
    ax.set_ylabel('bid_price_1')

    st.pyplot(fig)
