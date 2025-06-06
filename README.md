**How to work on this app:**

I created this project with the goal of keeping the development environment isolated, using Docker containers to accomplish this.

This Docker container packages all the required dependencies that we need to run our app running on a lightweight linux distribution with python 3.12

To work in this container, you must first build the image using the Dockerfile provided in the repository

To build the image, run this command in the terminal in the directory of where you installed the repo:

**docker build -t crisis-analysis .**

(include the dot it specifies that the current directory is where the image will build from)

After that is complete, it's time to run the image and create your first container:

To do this, run the command:

_**UPDATE**_

run **docker run -p 8051:8051 -v ${pwd}/proj-dev:/proj-dev crisis-analysis**

or **docker run -p 8051:8051 -v $(pwd)/proj-dev:/proj-dev crisis-analysis** on mac

This will run the container off the image that you specified (crisis-analysis) and bind port 8888 on your computer to port 8888 (-p tag) in the container for the Jupyter server to communicate through

**NEW**: The v tags will essentially let your container and the host pc share files from the directories that are specified. If you're on a linux based OS, replace brackets {} with () for the pwd command

This removes the need to copy over files after you're done working, just save and that's it. This also allows you to freely add data to the data folder (same goes for the app folder) without having to rebuild the image or even stop the running containerf.

Now in the terminal you should see that your container is running and you should be able to see the link that points to where you can access your Jupyter Notebooks ([your_ip_address]:8888)

UPDATES:
Exposed port 8050 to run the Dash app along with 8888 for the notebook
UPDATED 4/21/2025:
Exposed only port 8051 as that serves the main app, the rest are microservices that only communicate with each other
- This also means that port 8050 isn't bound so you can't run the notebook

Command to run the notebook is :
**jupyter notebook --ip=0.0.0.0 --port=8888 --no-browser --allow-root**
ONLY DO THIS IF YOU WANT TO MODIFY THE MODEL


**When running the app, you need to start all the microservices first:**
cd into proj-dev/app/live_demo and run the following scripts:
model_server.py (does all entity extraction and location standardization through the supabase db)
firehose_scraper_server.py (scrapes posts from bluesky)
entry.py (puts it all together and handles data storage and grouping)
dash_client.py (UI / frontend part) (instead of python run this command: gunicorn dash_client:server --bind 0.0.0.0:8051 --workers 4 --threads 2)

Now, the docker container just runs "sleep infinity", so you can essentially control what you want it to do.

Run gunicorn server instead of dash_client : gunicorn dash_client:server --bind 0.0.0.0:8051 --workers 4 --threads 2