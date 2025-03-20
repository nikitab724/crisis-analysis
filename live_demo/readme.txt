the models are too large to store on github so i'll provide download links:
https://drive.google.com/drive/folders/16uHLuTruCLmG8-O9RPqjVuexX3keaBTY?usp=drive_link
https://drive.google.com/drive/folders/1DWWrSj_2M82ra6piw4e1zff7F0n9rdrm?usp=drive_link
Download the entire folders from the above two links and save them to the same directory as all the other files.

first run scraper_server.py and model_server.py
If you have an nvidia GPU, its highly reccomended to install CUDA and a compatible version of pytorch that works with your CUDA version. https://pytorch.org/get-started/locally/
then run entry.py, this starts the process of scraping bluesky posts and processing the text from said posts.
then run dash_client.py for the web dashboard