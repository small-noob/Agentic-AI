# Pre-class setup — Windows

Please complete the following before class.

## 1. Recommended: use VS Code

1. Download and install the Windows version from the [VS Code download page](https://code.visualstudio.com/download).
2. Open `Introduction_ReAct_Learner.ipynb` in VS Code.
3. Click **Select Kernel** at the top right, then choose **Python Environments**.
4. Follow the installation prompt if VS Code asks for the Python or Jupyter extension.
5. Select an available Python environment and run the first cell.

This is the recommended way to complete the classroom exercise.

## 2. Alternative: use Jupyter Notebook without VS Code

You only need this step if you do not want to use VS Code. Open PowerShell and run:

```powershell
python -m pip install notebook
python -m notebook
```

If Jupyter opens in your browser, the installation is complete. See the [official Jupyter installation guide](https://jupyter.org/install) if needed.

## 3. Get a Zhipu API key

1. Go to the [Zhipu AI Open Platform](https://bigmodel.cn/) and register or sign in with a phone number, email address or WeChat.
2. Open the [**API Keys** page](https://bigmodel.cn/apikey/platform).
3. Select **New API Key**.
4. Copy the key and keep it private.

The classroom notebook will request the key through a hidden input when the live API is used. Do not write the key directly in the notebook, include it in a screenshot, or submit it with your work.
