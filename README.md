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

run **docker run -p 8888:8888 -v ${pwd}/app:/app -v ${pwd}/data:/data crisis-analysis**

This will run the container off the image that you specified (crisis-analysis) and bind port 8888 on your computer to port 8888 (-p tag) in the container for the Jupyter server to communicate through

**NEW**: The v tags will essentially let your container and the host pc share files from the directories that are specified. If you're on a linux based OS, replace \${pwd} with \$(pwd)

This removes the need to copy over files after you're done working, just save and that's it. This also allows you to freely add data to the data folder (same goes for the app folder) without having to rebuild the image or even stop the running containerf.

Now in the terminal you should see that your container is running and you should be able to see the link that points to where you can access your Jupyter Notebooks ([your_ip_address]:8888)

Good luck, let me know if anything is confusing you
