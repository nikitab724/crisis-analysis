**How to work on this app:**

I created this project with the goal of keeping the development environment isolated, using Docker containers to accomplish this.

This Docker container packages all the required dependencies that we need to run our app running on a lightweight linux distribution with python 3.12

To work in this container, you must first build the image using the Dockerfile provided in the repository

To build the image, run this command in the terminal in the directory of where you installed the repo:

**docker build -t crisis-analysis .**

(include the dot it specifies that the current directory is where the image will build from)

After that is complete, it's time to run the image and create your first container:

To do this, run the command:

**docker run --rm -p 8888:8888 crisis-analysis**

This will run the container that you specified (crisis-analysis) and bind port 8888 on your computer to port 8888 (-p tag) in the container for the Jupyter server to communicate through

The --rm tag specifies that this container will be removed after you close it

Now in the terminal you should see that your container is running and you should be able to see the link that points to where you can access your Jupyter Notebooks ([your_ip_address]:8888)

You can now work on the datasets and everything else that is currently in the repo (given that you added it in the data folder before building the image)

It is important to remember that Docker containers are not state machines (once you turn them off their memory is erased and any data on there too)

To ensure your work is saved locally on your pc, you need to run this command (basically run this any time you are done with some work and want to push it to the repo):

**docker cp [container_name]:app/dataset_test.ipynb ./app**

The cp command is bidirectional (read about it more by running "docker cp --help", but essentially you are copying a file from the container's memory over to yours)
**Replace the brackets with the actual container name** (not the image name "crisis-analysis" but the randomly generated name you get when you run the image). 
You can check the name by opening Docker desktop and viewing the name of the currently running container

Obviously, if you are working in a different Notebook then change the name of that too (dataset_test.ipynb by default)
Keep the ./app part the same as this specifies the destination for this file to be in the app folder with the other python file.

Good luck, let me know if anything is confusing you
